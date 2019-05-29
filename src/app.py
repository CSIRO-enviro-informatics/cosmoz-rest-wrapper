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
HERE_DIR = os.path.dirname(__file__)
sys.path.append(os.path.dirname(HERE_DIR))
from sanic import Sanic
from spf import SanicPluginsFramework
from sanic_cors.extension import cors
from sanic_restplus import restplus
from sanic_jinja2_spf import sanic_jinja2
from src.api import api

is_py36 = sys.version_info[0:3] >= (3, 6, 0)
#from src.functions import JSONEncoder_newdefault
#JSONEncoder_newdefault()

app = Sanic(__name__)
app.config.SWAGGER_UI_DOC_EXPANSION = "full"
spf = SanicPluginsFramework(app)
cors, cors_reg = spf.register_plugin(cors, origins='*')
sanic_jinja2, jinja2_reg = spf.register_plugin(sanic_jinja2, enable_async=is_py36)
restplus, restplus_reg = spf.register_plugin(restplus)

file_loc = os.path.abspath(os.path.join(HERE_DIR, "static/material_swagger.css"))
app.static(uri="/static/material_swagger.css", file_or_directory=file_loc,
           name="material_swagger")
restplus.register_api(restplus_reg, api)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9001, debug=False)
