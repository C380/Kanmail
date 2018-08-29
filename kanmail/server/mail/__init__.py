from collections import defaultdict
from threading import Lock

from kanmail.server.util import execute_threaded
from kanmail.settings import get_settings

from .account import Account
from .util import markdownify

ACCOUNTS = {}
GET_ACCOUNTS_LOCK = Lock()


def connect_all():
    def make_account(key, settings):
        return key, Account(key, settings)

    with GET_ACCOUNTS_LOCK:
        accounts = execute_threaded(make_account, [
            (key, settings)
            for key, settings in get_settings()['accounts'].items()
            if key not in ACCOUNTS
        ])

        for key, account in accounts:
            ACCOUNTS[key] = account


def get_accounts():
    # Ensure we're connected to all configured accounts
    connect_all()

    return ACCOUNTS.values()


def get_account(key):
    # Ensure we're connected to all configured accounts
    connect_all()

    return ACCOUNTS[key]


def get_all_folders():
    def get_folders(account):
        return account.name, account.get_folders()

    account_folder_names = execute_threaded(get_folders, [
        (account,)
        for account in get_accounts()
    ])

    meta = {}
    folder_names = []

    for account_name, names in account_folder_names:
        folder_names.extend(names)
        meta[account_name] = {
            'count': len(names),
        }

    return list(set(folder_names)), meta


def get_folder_emails(
    account_key, folder_name,
    query=None, reset=False, batch_size=None,
):
    '''
    Get (more) emails from a folder within an account.
    '''

    account = get_account(account_key)
    folder = account.get_folder(folder_name, query=query)

    emails, from_offset, to_offset = folder.get_emails(
        reset=reset,
        batch_size=batch_size,
    )

    meta = {
        'count': len(folder),
        'from': from_offset,
        'to': to_offset,
    }

    return emails, meta


def sync_folder_emails(account_key, folder_name, query=None):
    '''
    Get new emails and any deleted UIDs for a folder within an account.
    '''

    account = get_account(account_key)
    folder = account.get_folder(folder_name, query=query)

    emails, deleted_uids = folder.sync_emails()

    meta = {
        'count': len(folder),
    }

    return emails, deleted_uids, meta


def _get_folder_email_parts(account_key, folder_name, uid_parts):
    '''
    Get email parts (body parts) for a given folder and a given map of
    UID -> part ID. This happens in parallel for different part ID given, as
    IMAP cannot return different parts of different messages in each request.
    '''

    # Make map of part ID -> UIDs
    part_to_uid = defaultdict(list)

    for uid, part in uid_parts:
        part_to_uid[part].append(uid)

    account = get_account(account_key)
    folder = account.get_folder(folder_name)

    def get_email_parts(uids, part):
        email_parts = folder.get_email_parts(uids, part)
        return email_parts

    items = execute_threaded(get_email_parts, [
        (uids, part)
        for part, uids in part_to_uid.items()
    ])

    emails = {}

    for item in items:
        emails.update(item)

    return emails


def get_folder_email_texts(account_key, folder_name, uids):
    '''
    Get the best text part for a list of UIDs in a given folder. Will look for
    HTML then TEXT parts for each UID. Any text will be processed as markdown
    into HTML.

    Returns a dcit of uid -> HTML data.
    '''

    account = get_account(account_key)
    folder = account.get_folder(folder_name)

    uid_parts = []
    plaintext_uids = []

    uid_to_none = {}
    uid_to_content_ids = {}

    for uid in uids:
        parts = folder.cache.get_parts(uid)

        uid_to_content_ids[uid] = {
            part['content_id']: part_id
            for part_id, part in parts.items()
            if isinstance(part, dict) and part.get('content_id')
        }

        html = parts.get('html')
        text = parts.get('plain')

        if not html:
            plaintext_uids.append(uid)

        part_number = html or text

        if part_number:
            uid_parts.append((uid, part_number))
        # No text part? None!
        else:
            uid_to_none[uid] = None

    uid_part_data = _get_folder_email_parts(account_key, folder_name, uid_parts)
    uid_part_data.update(uid_to_none)

    uid_part_data_with_cids = {}

    for uid, data in uid_part_data.items():
        # Convert any plaintext items to html w/markdown
        if uid in plaintext_uids:
            data = markdownify(data)

        part_data_with_cids = {
            'html': data,
            'cid_to_part': uid_to_content_ids[uid],
        }

        uid_part_data_with_cids[uid] = part_data_with_cids
    return uid_part_data_with_cids


def get_folder_email_part(account_key, folder_name, uid, part_number):
    '''
    Get a specific part for a UID/part number in a given folder.
    '''

    account = get_account(account_key)
    folder = account.get_folder(folder_name)

    parts = folder.cache.get_parts(uid)

    if part_number not in parts:
        return None, None

    uid_part_data = _get_folder_email_parts(
        account_key, folder_name,
        [(uid, part_number)],
    )

    part_struct = parts[part_number]

    return (
        '{0}/{1}'.format(part_struct['type'], part_struct['subtype']).lower(),
        uid_part_data[uid],
    )


def _handle_folder_action(
    action_name, account_key, folder_name, message_uids,
    *args
):
    '''
    Perform a given action to a list of message UIDs on a given account/folder.
    Can also be passed extra args (eg folder to move to, for example).

    The methods below are "public" shortcuts for this.
    '''

    account = get_account(account_key)
    folder = account.get_folder(folder_name)

    action = getattr(folder, action_name)
    action(message_uids, *args)


def move_folder_emails(*args):
    _handle_folder_action('move_emails', *args)


def copy_folder_emails(*args):
    _handle_folder_action('copy_emails', *args)


def delete_folder_emails(*args):
    _handle_folder_action('delete_emails', *args)


def star_folder_emails(*args):
    _handle_folder_action('star_emails', *args)


def unstar_folder_emails(*args):
    _handle_folder_action('unstar_emails', *args)