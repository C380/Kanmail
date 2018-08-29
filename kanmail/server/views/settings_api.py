import webview

from flask import jsonify, request

from kanmail import settings
from kanmail.server.app import app
from kanmail.settings import (
    get_settings,
    set_cached_window_settings,
    update_settings,
)


@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    '''
    Get client settings.
    '''

    return jsonify(
        settings=get_settings(),
        settings_file=settings.SETTINGS_FILE,
    )


@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    '''
    Update client settings.
    '''

    request_data = request.get_json()

    update_settings(request_data)

    # Reload the main window now we've updated the settings
    if settings.IS_APP and request_data.pop('reload', None):
        webview.evaluate_js('window.location.reload()')

    return jsonify(saved=True)


@app.route('/api/window_settings', methods=['POST'])
def api_update_window_settings():
    request_data = request.get_json()

    # Importing this before creating the initial main window isn't allowed
    from webview.cocoa import BrowserView
    top_bar_height = BrowserView.DragBar.default_height + 1

    if 'height' in request_data:
        request_data['height'] += top_bar_height

    if 'top' in request_data:
        request_data['top'] -= top_bar_height

    set_cached_window_settings(**request_data)

    return jsonify(saved=True)