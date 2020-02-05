#!/bin/python3
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
import os
import sys
from os import putenv, getenv
from urllib.parse import quote_plus
from sanic.exceptions import Unauthorized
from sanic.response import HTTPResponse, text, redirect
from sanic import Sanic
from spf import SanicPluginsFramework
from spf.plugins.contextualize import contextualize
from sanic_cors.extension import cors
from sanic_restplus import restplus
from sanic_jinja2_spf import sanic_jinja2

HERE_DIR = os.path.dirname(__file__)
if HERE_DIR not in sys.path:
    sys.path.append(os.path.dirname(HERE_DIR))
from api import api
from apikey import check_apikey_valid, test_apikey, create_apikey_from_access_token
from util import PY_36, load_env
import oauth1_client

load_env()
#from src.functions import JSONEncoder_newdefault
#JSONEncoder_newdefault()
OVERRIDE_SERVER_NAME = getenv("SANIC_OVERRIDE_SERVER_NAME", "localhost:9001")
print("Using OVERRIDE_SERVER_NAME: {}".format(OVERRIDE_SERVER_NAME))
PROXY_ROUTE_BASE = getenv("SANIC_PROXY_ROUTE_BASE", "")
print("Using SANIC_PROXY_ROUTE_BASE: {}".format(PROXY_ROUTE_BASE))
SANIC_SERVER_NAME = getenv("SANIC_SERVER_NAME", "")
app = Sanic(__name__)
app.config.SWAGGER_UI_DOC_EXPANSION = "full"
if len(OVERRIDE_SERVER_NAME) and len(SANIC_SERVER_NAME) < 1:
   OR_SERVER_NAME_PARTS = OVERRIDE_SERVER_NAME.split(":")
   SANIC_SERVER_NAME = OR_SERVER_NAME_PARTS[0]
   if len(OR_SERVER_NAME_PARTS) > 1:
       port = int(OR_SERVER_NAME_PARTS[1])
       if port != 80 and port != 443:
           SANIC_SERVER_NAME = "{}:{}".format(SANIC_SERVER_NAME, str(port))
print("Using SANIC_SERVER_NAME: {}".format(SANIC_SERVER_NAME))
if len(SANIC_SERVER_NAME):
    app.config['SERVER_NAME'] = SANIC_SERVER_NAME
spf = SanicPluginsFramework(app)
cors, cors_reg = spf.register_plugin(cors, origins='*')
ctx = spf.register_plugin(contextualize)
sanic_jinja2, jinja2_reg = spf.register_plugin(sanic_jinja2, enable_async=PY_36)
restplus, restplus_reg = spf.register_plugin(restplus)
c = oauth1_client.create_client(app)
file_loc = os.path.abspath(os.path.join(HERE_DIR, "static/material_swagger.css"))
app.static(uri="/static/material_swagger.css", file_or_directory=file_loc,
           name="material_swagger")
restplus.register_api(restplus_reg, api)

@ctx.route("/apikey", methods=["GET", "HEAD", "OPTIONS"])
async def apikey(request, context):
    if request.method == "OPTIONS":
        return HTTPResponse(None, 200, None)
    existing_apikey = request.headers.get("X-API-Key")
    if existing_apikey:
        return await checkaccesskey(request, existing_apikey)
    shared_context = context.shared
    shared_request_context = shared_context.request[id(request)]
    session = shared_request_context.get('session', {})
    state = session.get('oauth1_state', None)
    if not state or ('access_token_session_key' not in state):
        after_this = context.url_for('apikey', _external=True, _scheme='http',
                                  _server=OVERRIDE_SERVER_NAME)
        redir_to = app.url_for('create_oauth', _external=True, _scheme='http',
                               _server=OVERRIDE_SERVER_NAME)
        if len(PROXY_ROUTE_BASE):
            after_this = after_this.replace("/apikey", "/{}apikey".format(
                PROXY_ROUTE_BASE))
            redir_to = redir_to.replace("/create_oauth", "/{}create_oauth".format(
                PROXY_ROUTE_BASE))
        redir_to = "{}?after_authorized={}".format(redir_to, quote_plus(after_this))
        return redirect(redir_to)
    oauth_resp = session.get(state['access_token_session_key'], None)
    if not oauth_resp:
        raise Unauthorized("Could not create a new API Key")
    client_name = state.get('remote_app', "client1")
    new_api_key = await create_apikey_from_access_token(client_name, "1.0a", oauth_resp)
    return text(new_api_key, 200)


@app.route("/checkapikey", methods=["GET", "HEAD", "OPTIONS"])
async def checkapikey(request):
    if request.method == "OPTIONS":
        return HTTPResponse(None, 200, None)
    existing_apikey = request.headers.get("X-API-Key")
    if existing_apikey:
        return await checkaccesskey(request, existing_apikey)
    raise Unauthorized("Please include X-API-Key")


@app.route("/checkapikey/<api_key>", methods=["GET", "HEAD", "OPTIONS"])
async def checkaccesskey(request, api_key):
    if request.method == "OPTIONS":
        return HTTPResponse(None, 200, None)
    if api_key is None:
        raise Unauthorized("Please include API Key in query")
    valid, message = await check_apikey_valid(api_key)
    if not valid:
        if request.method == "HEAD":
            return HTTPResponse(None, 401, None)
        else:
            if message:
                raise Unauthorized("API Key validation error: {}".format(message))
            raise Unauthorized("API Key is not valid")
    works, message = await test_apikey(api_key)
    if not works:
        if request.method == "HEAD":
            return HTTPResponse(None, 401, None)
        else:
            if message:
                raise Unauthorized("API Key Test error: {}".format(message))
            raise Unauthorized("API Key is not valid but does not work. Perhaps the OAuth access key has been revoked.")
    return HTTPResponse(message, 200)


if __name__ == "__main__":
    server_name = OVERRIDE_SERVER_NAME or "localhost:9001"
    if ":" in server_name:
        host, port = server_name.split(":", 1)
    else:
        host = server_name
        port = 9001
    app.run(host=host, port=port, debug=True, auto_reload=False)
