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
import datetime
import sys
PY_36 = sys.version_info[0:3] >= (3, 6, 0)


#NOTE, These are both ALWAYS UTC!

def datetime_to_iso(_d, include_micros=None):
    _d = _d.astimezone(datetime.timezone.utc)
    if include_micros is None:
        include_micros = _d.microsecond != 0
    if include_micros:
        return _d.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        return _d.strftime("%Y-%m-%dT%H:%M:%SZ")

def datetime_to_date_string(_d):
    _d = _d.astimezone(datetime.timezone.utc)
    return _d.strftime("%Y-%m-%d")

def datetime_from_iso(_d):
    try:
        _d = datetime.datetime.strptime(_d, "%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:
        _d =datetime.datetime.strptime(_d, "%Y-%m-%dT%H:%M:%SZ")
    return _d.replace(tzinfo=datetime.timezone.utc)



def load_env():
    """
    Execute the dotenv load
    :return:
    """
    loaded = load_env.loaded
    if loaded:
        return
    import dotenv
    dotenv.load_dotenv()
    load_env.loaded = True

if not hasattr(load_env, 'loaded'):
    setattr(load_env, 'loaded', False)
