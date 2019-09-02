# -*- coding: utf-8 -*-
"""
Copyright 2019 CSIRO Land and Water

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from inspect import isawaitable
from json import dumps, loads
from os import getenv
from sanic.response import redirect, json, text
from sanic.exceptions import SanicException
from spf import SanicPluginsFramework
from spf.plugins.contextualize import contextualize
from sanic_oauthlib.client import oauthclient
from sanic_session_spf import session as session_plugin
from filesystem_session_interface import FilesystemSessionInterface
from util import load_env


#having these in a module-local _hopefully_ shouldn't be a problem
#using them async might be an issue, but maybe not
REMOTES = {}

def add_oauth_plugin(app):
    spf = SanicPluginsFramework(app)
    try:
        oauth = spf.register_plugin(oauthclient)
    except ValueError as v:
        _, oauth = v
    return oauth

def create_remote(app, oauth=None):
    if not oauth:
        oauth = add_oauth_plugin(app)
    consumer_key = getenv("OAUTH1_CSIRO_LDAP_CONSUMER_KEY", "example1")
    consumer_secret = getenv("OAUTH1_CSIRO_LDAP_CONSUMER_SECRET", "password1")
    remote = oauth.remote_app(
        'csiro-to-ldap',
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        request_token_params={'realm': 'profile'},
        base_url='https://oauth.esoil.io/api/',
        request_token_url='https://oauth.esoil.io/oauth/request_token',
        access_token_method='GET',
        access_token_url='https://oauth.esoil.io/oauth/access_token',
        authorize_url='https://oauth.esoil.io/oauth/authorize'
    )
    REMOTES['csiro-to-ldap'] = remote
    return remote


def create_client(app, oauth=None, remote=None):
    load_env()
    if not oauth:
        oauth = add_oauth_plugin(app)
    if not remote:
        remote = create_remote(app, oauth)
    spf = SanicPluginsFramework(app)
    try:
        session_interface = FilesystemSessionInterface()
        spf.register_plugin(session_plugin, interface=session_interface)
    except ValueError:
        pass
    try:
        ctx = spf.register_plugin(contextualize)
    except ValueError as v:
        _, ctx = v.args

    # @app.route('/')
    # async def index(request):
    #     if 'csiro-to-ldap_oauth' in session:
    #         ret = await oauth.get('email')
    #         if isinstance(ret.data, dict):
    #             return json(ret.data)
    #         return str(ret.data)
    #     return redirect(app.url_for('login'))

    @app.route('/create_oauth')
    @remote.autoauthorize
    async def create_oauth(request, context):
        try:
            callback = request.url_for('authorized')
        except AttributeError:
            override_server_name = getenv("SANIC_OVERRIDE_SERVER_NAME", "localhost:9001")
            callback = request.app.url_for('authorized', _external=True, _scheme='http', _server=override_server_name)
        after_this = request.args.get("after_authorized", "/apikey")
        state = {"remote_app": 'csiro-to-ldap', "after_authorized": after_this}
        #Oauth1 cannot put state in the request, we need to put it in the session
        shared_context = context.shared
        shared_request_context = shared_context.request[id(request)]
        session = shared_request_context.get('session', {})
        session['oauth1_state'] = state
        return {'callback': callback}

    @app.route('/logout')
    def logout(request):
        session.pop('csiro-to-ldap_oauth', None)
        return redirect(app.url_for('index'))

    @app.route('/authorized')
    @remote.authorized_handler
    async def authorized(request, data, context):
        if data is None:
            return 'Access denied: error=%s' % (
                request.args['error']
            )
        resp = {k: v[0] for k, v in data.items()}

        shared_context = context.shared
        shared_request_context = shared_context.request[id(request)]
        session = shared_request_context.get('session', {})
        state = session.get('oauth1_state', None)
        after_authorized = state.get('after_authorized', "/apikey") if state else "/apikey"
        if 'oauth_token' in resp:
            session['csiro-to-ldap_oauth'] = resp
            if state:
                state['access_token_session_key'] = "csiro-to-ldap_oauth"
        session['oauth1_state'] = state
        return redirect(after_authorized)

    @app.route('/method/<name>')
    async def method(request, name):
        func = getattr(remote, name)
        ret = func('method')
        if isawaitable(ret):
            ret = await ret
        return text(ret.raw_data)

    def make_token_getter(_remote):
        context = oauth.context
        shared_context = context.shared
        @_remote.tokengetter
        async def get_oauth_token():
            nonlocal context, shared_context
            raise NotImplementedError("Out-of-order token getter is not implemented. Pass the token to the requester when its required.")
            # if 'dev_oauth' in session:
            #     resp = session['dev_oauth']
            #     return resp['oauth_token'], resp['oauth_token_secret']

    make_token_getter(remote)
    return remote


#TODO: maybe cache this to prevent repeated hits to the api?
async def test_oauth_token(client_name, access_token, access_token_secret):
    remote = REMOTES.get(client_name, None)
    if remote is None:
        raise RuntimeError("Cannot get oauth1 remote with name \"{}\"".format(client_name))
    resp = await remote.get("/api/method", token=(access_token, access_token_secret))
    if resp.data is not None and isinstance(resp.data, dict):
        method = str(resp.data.get("method")).upper()
        if method == "GET":
            return True
    return False