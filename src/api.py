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
from collections import OrderedDict
import datetime
import aiofiles
from sanic import response
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from sanic_restplus import Api, Resource, fields
from sanic.response import json, text, stream, HTTPResponse
from sanic.exceptions import ServiceUnavailable, MethodNotSupported
from sanic_jinja2_spf import sanic_jinja2
from orjson import dumps as fast_dumps, OPT_NAIVE_UTC, OPT_UTC_Z
from functools import partial

import config
from config import TRUTHS
from functions import get_observations_influx,\
    STATION_COLLECTION, get_station_mongo, get_stations_mongo,\
    CALIBRATION_COLLECTION, get_calibration_mongo, get_station_calibration_mongo,\
    ANNOTATION_COLLECTION, get_annotation_mongo, get_station_annotations_mongo,\
    insert_file_stream, write_file_to_stream,\
    get_last_observations_influx, is_unique_val, insert, update
from util import PY_36, datetime_from_iso
from auth_functions import token_auth
from models import StationSchema, CalibrationSchema, AnnotationSchema
from json_api_helpers import format_errors
from marshmallow import ValidationError

orjson_option = OPT_NAIVE_UTC | OPT_UTC_Z

security_defs = {
    # X-API-Key: abcdef12345
    'APIKeyHeader': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'X-API-Key'
    },
    'APIKeyQueryParam': {
        'type': 'apiKey',
        'in': 'query',
        'name': 'api_key'
    },
    'AuthToken': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'Authorization'
    }
}

api = Api(title="CSIRO Cosmoz REST Interface",
          prefix='', doc='/doc',
          authorizations=security_defs,
          default_mediatype="application/json",
          additional_css="/static/material_swagger.css")
ns = api.default_namespace

MAX_RETURN_COUNT = 2147483647  # Highest 32bit signed int
EARLIEST_DATETIME = datetime.now(tz=timezone.utc) - timedelta(days=36525)


def get_jinja2_for_api(_a):
    if _a.spf_reg is None:
        raise RuntimeError("API is not registered on a Sanic App.")
    (s, _, _) = _a.spf_reg
    reg = sanic_jinja2.find_plugin_registration(s)
    assoc = sanic_jinja2.AssociatedTuple(sanic_jinja2, reg)
    return assoc

def get_accept_mediatypes_in_order(request):
    """
    Reads an Accept HTTP header and returns an array of Media Type string in descending weighted order

    :return: List of URIs of accept profiles in descending request order
    :rtype: list
    """
    try:
        # split the header into individual URIs, with weights still attached
        mtypes_list = request.headers['Accept'].split(',')
        # remove \s
        mtypes_list = [x.replace(' ', '').strip() for x in mtypes_list]

        # split off any weights and sort by them with default weight = 1
        weighted_mtypes = []
        for mtype in mtypes_list:
            mtype_parts = iter(mtype.split(";"))
            mimetype = next(mtype_parts)
            qweight = None
            try:
                while True:
                    part = next(mtype_parts)
                    if part.startswith("q="):
                        qweight = float(part.replace("q=", ""))
                        break
            except StopIteration:
                if qweight is None:
                    qweight = 1.0
            weighted_mtypes.append((qweight, mimetype))

        # sort profiles by weight, heaviest first
        weighted_mtypes.sort(reverse=True)

        return [x[1] for x in weighted_mtypes]
    except Exception as e:
        raise RuntimeError(
            'You have requested a Media Type using an Accept header that is incorrectly formatted.')

def match_accept_mediatypes_to_provides(request, provides):
    order = get_accept_mediatypes_in_order(request)
    for i in order:
        if i in provides:
            return i
    # try to match wildcards
    for i in order:
        if i == "*/*":
            return provides[0]
        elif i.endswith("/*"):
            check_for = i.replace("/*", "/")
            for j in provides:
                if j.startswith(check_for):
                    return j
        elif i.startswith("*/"):
            check_for = i.replace("*/", "/")
            for j in provides:
                if j.endswith(check_for):
                    return j
    return None

def get_response_type(request, provides):
    return_type = match_accept_mediatypes_to_provides(request, provides)

    format = request.args.getlist('format', None)
    if not format:
        format = request.args.getlist('_format', None)
    if format:
        format = next(iter(format))
        if format in provides:
            return_type = format

    return return_type

async def create_response(request, content, response_type, api, template_map={}):
    if response_type == "application/json":
        return HTTPResponse(None, status=200, content_type=response_type, body_bytes=fast_dumps(content, option=orjson_option))

    headers = {'Content-Type': response_type}
    jinja2 = get_jinja2_for_api(api)
    if response_type in template_map:
        template = template_map[response_type]
    else:
        raise NotImplementedError("Cannot determine template name to use for response type.")
    if PY_36:
        return await jinja2.render_async(template, request, headers=headers, **content)
    else:
        return jinja2.render(template, request, headers=headers, **content)

async def get_many_obj_reponse(request, response_types, async_partial_func, api, template_map={}):
    response_type = get_response_type(request, response_types)

    if response_type is None:
        raise MethodNotSupported("Please use a valid accept type.")

    if response_type == "application/json":
        property_filter = request.args.getlist('property_filter', None)
        if property_filter:
            property_filter = str(next(iter(property_filter))).split(',')
            property_filter = [p for p in property_filter if len(p)]
    else:
        # CSV and TXT get all properties, regardless of property_filter, as it might break templates
        property_filter = "*"

    count = request.args.getlist('count', None)
    if count:
        count = min(int(next(iter(count))), MAX_RETURN_COUNT)
    else:
        count = 1000

    offset = request.args.getlist('offset', None)
    if offset:
        offset = min(int(next(iter(offset))), MAX_RETURN_COUNT)
    else:
        offset = 0

    obs_params = {
        "property_filter": property_filter,
        "count": count,
        "offset": offset,
    }

    json_safe = 'orjson' if response_type == "application/json" else False
    jinja_safe = 'txt' if response_type == "text/plain" else False
    jinja_safe = 'csv' if response_type == "text/csv" else jinja_safe
    
    result = await async_partial_func(params=obs_params, json_safe=json_safe, jinja_safe=jinja_safe)

    return await create_response(request, result, response_type, api, template_map)

async def get_obj_reponse(request, response_types, async_partial_func, api, template_map={}):
    response_type = get_response_type(request, response_types)

    if response_type is None:
        raise MethodNotSupported("Please use a valid accept type.")

    if response_type == "application/json":
        property_filter = request.args.getlist('property_filter', None)
        if property_filter:
            property_filter = str(next(iter(property_filter))).split(',')
            property_filter = [p for p in property_filter if len(p)]
    else:
        # CSV and TXT get all properties, regardless of property_filter, as it might break templates
        property_filter = "*"

    obs_params = {
        "property_filter": property_filter,
    }

    json_safe = 'orjson' if response_type == "application/json" else False
    jinja_safe = 'txt' if response_type == "text/plain" else False
    jinja_safe = 'csv' if response_type == "text/csv" else jinja_safe
    
    result = await async_partial_func(params=obs_params, json_safe=json_safe, jinja_safe=jinja_safe)

    return await create_response(request, result, response_type, api, template_map)

async def generic_update_request(collection, selector, model_name, raw_doc, schema_cls):
    try:
        cleaned = schema_cls().load(raw_doc)            
    except ValidationError as err:
        errors = err.messages
        payload = format_errors(schema_cls(), errors, False)
        return json(payload, status=422)
    
    await update(collection, selector, cleaned)
    new_obj = schema_cls().dump(cleaned)
    response_dict = {
        model_name: new_obj
    }
    return json(response_dict)

async def generic_create_request(collection, model_name, raw_doc, schema_cls):
    try:
        cleaned = schema_cls().load(raw_doc)            
    except ValidationError as err:
        errors = err.messages
        payload = format_errors(schema_cls(), errors, False)
        return json(payload, status=422)
        
    id = await insert(collection, cleaned)

    new_obj = schema_cls().dump(cleaned)
    new_obj['id'] = str(id)
    response_dict = {
        model_name: new_obj
    }

    return json(response_dict)

@ns.route('/stations')
class Stations(Resource):
    accept_types = ["application/json", "text/csv", "text/plain"]
    '''Gets a JSON representation of all sites in the COSMOZ database.'''
    @ns.doc('get_stations', params=OrderedDict([
        ("property_filter", {"description": "Comma delimited list of properties to retrieve.\n\n"
                             "_Enter * for all_.",
                             "required": False, "type": "string", "format": "text"}),
        ("count", {"description": "Number of records to return.",
                   "required": False, "type": "number", "format": "integer", "default": 100}),
        ("offset", {"description": "Skip number of records before reading count.",
                    "required": False, "type": "number", "format": "integer", "default": 0}),
    ]), security=None)
    @ns.produces(["application/json"])
    async def get(self, request, *args, **kwargs):
        '''Get cosmoz stations.'''
        return await get_many_obj_reponse(request, self.accept_types, get_stations_mongo, self.api)

    @ns.doc('post_station', security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    async def post(self, request, *args, **kwargs):
        '''Add new cosmoz station.'''
        if not "station" in request.json:
            return text("station must be in the payload", status=400)                    
        
        raw = request.json["station"]
        if 'site_no' in raw and not await is_unique_val(STATION_COLLECTION, 'site_no', int(raw['site_no'])):
            err = ValidationError({'site_no': ["Value already in use"]})
            payload = format_errors(schema_cls(), err.messages, False)
            return json(payload, status=422)

        return await generic_create_request(STATION_COLLECTION, 'station', raw, StationSchema)


@ns.route('/stations/<station_no>')
@ns.param('station_no', "Station Number", type="number", format="integer")
@ns.response(404, 'Station not found')
class Station(Resource):
    accept_types = ["application/json", "text/csv", "text/plain"]
    '''Gets site date for station_no.'''

    @ns.doc('get_station', params=OrderedDict([
        ("property_filter", {"description": "Comma delimited list of properties to retrieve.\n\n"
                             "_Enter * for all_.",
                             "required": False, "type": "string", "format": "text"}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, station_no=None, **kwargs):
        '''Get cosmoz station.'''
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
        get_station_func = partial(get_station_mongo, station_no)

        return await get_obj_reponse(request, self.accept_types, get_station_func, self.api, {
            "text/plain": 'site_values_txt.html'
        })


    @ns.doc('put_station', security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    @ns.produces(accept_types)
    async def put(self, request, *args, station_no=None, **kwargs):
        '''Update cosmoz station calibration'''
        if not request.json: 
            return text("You need a json body with the request", status=400)
        if "station" not in request.json:
            return text("'station' must be in the body payload", status=400)

        return await generic_update_request(STATION_COLLECTION, {'site_no': int(station_no)}, 'station', request.json["station"], StationSchema)


@ns.route('/calibrations')
@ns.param('station_no', "Station Number", type="number", format="integer", _in="query")
@ns.response(404, 'Calibrations not found')
class Calibrations(Resource):
    accept_types = ["application/json", "text/csv", "text/plain"]
    '''Gets site date for station_no.'''

    @ns.doc('get_station_cal', params=OrderedDict([
        ("property_filter", {
            "description": "Comma delimited list of properties to retrieve.\n\n"
                           "_Enter * for all_.",
            "required": False, "type": "string", "format": "text"}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, **kwargs):
        '''Get cosmoz station calibrations.'''
        station_no = request.args.get('station_no', None)
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)

        get_cals_func = partial(get_station_calibration_mongo, station_no)

        return await get_obj_reponse(request, self.accept_types, get_cals_func, self.api, {
            "text/csv": 'site_data_cal_csv.html',
            "text/plain": 'site_data_cal_txt.html'
        })


    @ns.doc('post_calibration', security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    async def post(self, request, *args, **kwargs):
        '''Add new cosmoz station calibration.'''
        if not "calibration" in request.json:
            return text("calibration must be in the payload", status=400)
        
        return await generic_create_request(CALIBRATION_COLLECTION, 'calibration',  request.json["calibration"], CalibrationSchema)

@ns.route('/calibrations/<c_id>')
@ns.param('c_id', "Calibration ID", type="string")
@ns.response(404, 'Calibration not found')
class Calibration(Resource):
    accept_types = ["application/json", "text/csv", "text/plain"]

    @ns.doc('get_calibration', params=OrderedDict([
        ("property_filter", {
            "description": "Comma delimited list of properties to retrieve.\n\n"
                           "_Enter * for all_.",
            "required": False, "type": "string", "format": "text"}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, c_id=None, **kwargs):
        '''Get cosmoz station calibrations.'''
        if c_id is None:
            raise RuntimeError("id is mandatory.")

        get_calibration_func = partial(get_calibration_mongo, c_id)

        return await get_obj_reponse(request, self.accept_types, get_calibration_func, self.api, {
            "text/csv": 'site_data_cal_csv_single.html', 
            "text/plain": 'site_data_cal_txt_single.html'
        })

    @ns.doc('put_calibration', security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    async def put(self, request, *args, c_id=None, **kwargs):
        '''Update cosmoz station calibration'''
        if not "calibration" in request.json:
            text("calibration must be in the payload", status=400)

        return await generic_update_request(CALIBRATION_COLLECTION, c_id, 'calibration', request.json["calibration"], CalibrationSchema)

@ns.route('/stations/<station_no>/observations')
@ns.param('station_no', "Station Number", type="number", format="integer")
class Observations(Resource):
    accept_types = ["application/json", "text/csv", "text/plain"]
    '''Gets a JSON representation of observation records in the COSMOZ database.'''

    @ns.doc('get_records', params=OrderedDict([
        ("processing_level", {"description": "Query the table for this processing level.\n\n"
                              "(0, 1, 2, 3, or 4).",
                              "required": False, "type": "number", "format": "integer", "default": 4}),
        ("startdate", {"description": "Start of the date/time range, in ISO8601 format.\n\n"
                       "_Eg: `2017-06-01T00:00:00Z`_\n\n",
                       "required": False, "type": "string", "format": "text"}),
        ("enddate", {"description": "End of the date/time range, in ISO8601 format.\n\n"
                     "_Eg: `2017-07-01T23:59:59Z`_\n\n",
                     "required": False, "type": "string", "format": "text"}),
        ("property_filter", {"description": "Comma delimited list of properties to retrieve.\n\n"
                             "_Enter * for all_.",
                             "required": False, "type": "string", "format": "text"}),
        ("aggregate", {"description": "Average observations over a given time period.\n\n"
                                      "Eg. `2h` or `3m` or `1d`",
                       "required": False, "type": "string", "format": "text"}),
        ("excel_compat", {"description": "Use MS Excel compatible datetime column in CSV and TXT responses.",
                          "required": False, "type": "boolean", "default": False}),
        ("count", {"description": "Number of records to return.",
                   "required": False, "type": "number", "format": "integer", "default": 2000}),
        ("offset", {"description": "Skip number of records before reading count.",
                    "required": False, "type": "number", "format": "integer", "default": 0}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, station_no=None, **kwargs):
        '''Get cosmoz records.'''
        return_type = match_accept_mediatypes_to_provides(request,
                                                          self.accept_types)
        format = request.args.getlist('format', None)
        if not format:
            format = request.args.getlist('_format', None)
        if format:
            format = next(iter(format))
            if format in self.accept_types:
                return_type = format
        if return_type is None:
            return_type = "application/json"
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
        processing_level = request.args.getlist('processing_level', None)
        if processing_level:
            processing_level = int(next(iter(processing_level)))
        else:
            processing_level = 4
        not_json = return_type != "application/json"
        if not not_json:
            property_filter = request.args.getlist('property_filter', None)
            if property_filter:
                property_filter = str(next(iter(property_filter))).split(',')
                property_filter = [p for p in property_filter if len(p)]
        else:
            property_filter = "*"
        excel_compat = request.args.getlist('excel_compat', [False])[0] in TRUTHS
        aggregate = request.args.getlist('aggregate', None)
        if aggregate:
            aggregate = str(next(iter(aggregate)))
        nowtime = datetime.utcnow().astimezone(timezone.utc)
        startdate = request.args.getlist('startdate', None)
        if startdate:
            startdate = next(iter(startdate))
        else:
            if not not_json:
                startdate = (nowtime + timedelta(days=-365)) \
                    .replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                startdate = EARLIEST_DATETIME
        enddate = request.args.getlist('enddate', None)
        if enddate:
            enddate = next(iter(enddate))
        else:
            enddate = nowtime.replace(hour=23, minute=59, second=59, microsecond=0)
        count = request.args.getlist('count', None)
        if not not_json:
            fallback_count = 2000
        else:
            fallback_count = MAX_RETURN_COUNT
        if count:
            try:
                count = min(int(next(iter(count))), MAX_RETURN_COUNT)
            except ValueError:
                count = fallback_count
        else:
            count = fallback_count
        offset = request.args.getlist('offset', None)
        fallback_offset = 0
        if offset:
            try:
                offset = min(int(next(iter(offset))), MAX_RETURN_COUNT)
            except ValueError:
                offset = fallback_offset
        else:
            offset = fallback_offset
        obs_params = {
            "processing_level": processing_level,
            "property_filter": property_filter,
            "aggregate": aggregate,
            "startdate": startdate,
            "enddate": enddate,
            "count": count,
            "offset": offset,
        }
        if not not_json:
            json_safe = 'orjson'
            try:
                res = get_observations_influx(station_no, obs_params, json_safe, False)
                return HTTPResponse(None, status=200, content_type=return_type, body_bytes=fast_dumps(res, option=orjson_option))
            except Exception as e:
                print(e)
                raise e
        headers = {'Content-Type': return_type}
        jinja2 = get_jinja2_for_api(self.api)
        if return_type == "text/csv":
            if processing_level == 0:
                template = "raw_data_csv.html"
            else:
                template = "level{}_data_csv.html".format(processing_level)
            headers['Content-Disposition'] = "attachment; filename=\"station{}_level{}.csv\"" \
                .format(str(station_no), str(processing_level))
        elif return_type == "text/plain":
            headers = {'Content-Type': return_type}
            if processing_level == 0:
                template = "raw_data_txt.html"
            else:
                template = "level{}_data_txt.html".format(processing_level)
            headers['Content-Disposition'] = "attachment; filename=\"station{}_level{}.txt\"" \
                .format(str(station_no), str(processing_level))
        else:
            raise RuntimeError("Invalid Return Type")

        async def streaming_fn(response):
            nonlocal template
            nonlocal station_no
            nonlocal obs_params
            nonlocal request
            nonlocal excel_compat
            res = get_observations_influx(station_no, obs_params, False, excel_compat)
            if PY_36:
                r = await jinja2.render_string_async(template, request, **res)
            else:
                r = jinja2.render_string(template, request, **res)
            await response.write(r)

        return stream(streaming_fn, status=200, headers=headers, content_type=return_type)


@ns.route('/stations/<station_no>/lastobservations')
@ns.param('station_no', "Station Number", type="number", format="integer")
class LastObservations(Resource):
    '''Gets a JSON representation of recent observation records in the COSMOZ database.'''
    accept_types = ["application/json", "text/csv", "text/plain"]
    @ns.doc('get_records', params=OrderedDict([
        ("processing_level", {"description": "Query the table for this processing level.\n\n"
                              "(0, 1, 2, 3, or 4).",
                              "required": False, "type": "number", "format": "integer", "default": 4}),
        ("property_filter", {"description": "Comma delimited list of properties to retrieve.\n\n"
                             "_Enter * for all_.",
                             "required": False, "type": "string", "format": "text"}),
        ("excel_compat", {"description": "Use MS Excel compatible datetime column in CSV and TXT responses.",
                          "required": False, "type": "boolean", "default": False}),
        ("count", {"description": "Number of records to return.",
                   "required": False, "type": "number", "format": "integer", "default": 1}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, station_no=None, **kwargs):
        '''Get recent cosmoz records.'''
        return_type = match_accept_mediatypes_to_provides(request,
                                                          self.accept_types)
        format = request.args.getlist('format', None)
        if not format:
            format = request.args.getlist('_format', None)
        if format:
            format = next(iter(format))
            if format in self.accept_types:
                return_type = format
        if return_type is None:
            return_type = "application/json"
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
        processing_level = request.args.getlist('processing_level', None)
        if processing_level:
            processing_level = int(next(iter(processing_level)))
        else:
            processing_level = 4
        excel_compat = request.args.getlist('excel_compat', [False])[0] in TRUTHS
        not_json = return_type != "application/json"
        if not not_json:
            property_filter = request.args.getlist('property_filter', None)
            if property_filter:
                property_filter = str(next(iter(property_filter))).split(',')
                property_filter = [p for p in property_filter if len(p)]
        else:
            property_filter = "*"
        count = request.args.getlist('count', None)
        if not not_json:
            fallback_count = 2000
        else:
            fallback_count = MAX_RETURN_COUNT
        if count:
            try:
                count = min(int(next(iter(count))), MAX_RETURN_COUNT)
            except ValueError:
                count = fallback_count
        else:
            count = fallback_count
        obs_params = {
            "processing_level": processing_level,
            "property_filter": property_filter,
            "count": count,
        }
        if not not_json:
            json_safe = 'orjson'
            try:
                res = get_last_observations_influx(station_no, obs_params, json_safe, False)
                return HTTPResponse(None, status=200, content_type=return_type, body_bytes=fast_dumps(res, option=orjson_option))
            except Exception as e:
                print(e)
                raise e
        headers = {'Content-Type': return_type}
        jinja2 = get_jinja2_for_api(self.api)
        if return_type == "text/csv":
            if processing_level == 0:
                template = "raw_data_csv.html"
            else:
                template = "level{}_data_csv.html".format(processing_level)
            headers['Content-Disposition'] = "attachment; filename=\"station{}_level{}.csv\"" \
                .format(str(station_no), str(processing_level))
        elif return_type == "text/plain":
            headers = {'Content-Type': return_type}
            if processing_level == 0:
                template = "raw_data_txt.html"
            else:
                template = "level{}_data_txt.html".format(processing_level)
            headers['Content-Disposition'] = "attachment; filename=\"station{}_level{}.txt\"" \
                .format(str(station_no), str(processing_level))
        else:
            raise RuntimeError("Invalid Return Type")

        async def streaming_fn(response):
            nonlocal template
            nonlocal station_no
            nonlocal obs_params
            nonlocal request
            nonlocal excel_compat
            res = get_last_observations_influx(station_no, obs_params, False, excel_compat)
            if PY_36:
                r = await jinja2.render_string_async(template, request, **res)
            else:
                r = jinja2.render_string(template, request, **res)
            await response.write(r)

        return stream(streaming_fn, status=200, headers=headers, content_type=return_type)

@ns.route("/metrics", doc=False)
class Metrics(Resource):
    async def post(self, request, context):
        rcontext = context.for_request(request)
        shared_context = context.shared
        shared_rcontext = shared_context.for_request(request)

        action = request.args.getlist('action', None)
        if action:
            action = next(iter(action))
        else:
            raise RuntimeError("action is mandatory.")
        metrics_override = {
            'method': 'GET',
            'status': 200,
            'skip_response': True,
        }
        referer = request.headers.getall('Referer')
        if referer:
            referer = next(iter(referer))
            try:
                (scheme, netloc, path, query, fragment) = urlsplit(referer)
                metrics_override['host'] = netloc
                metrics_override['path'] = path
            except:
                pass
        else:
            # No referer, this will be hard to track
            pass
        if action == "page_visit":
            time = request.args.getlist('time', None)
            if time:
                time = next(iter(time))
                try:
                    metrics_override['datetime_start_iso'] = time
                    t = datetime_from_iso(time)
                    metrics_override['timestamp_start'] = t.timestamp()
                    metrics_override['datetime_start'] = t
                except Exception:
                    pass
            page = request.args.getlist('page', None)
            if page:
                page = next(iter(page))
                metrics_override['path'] = page
            query = request.args.getlist('query', None)
            if query:
                query = next(iter(query))
            else:
                query = None
            metrics_override['qs'] = query
        else:
            raise NotImplementedError(action)
        shared_rcontext['override_metrics'] = metrics_override
        res = {"result": "success"}
        return HTTPResponse(None, status=200, content_type='application/json', body_bytes=fast_dumps(res, option=orjson_option))

@ns.route("/users/me")
class Users(Resource):
    @ns.doc('get_userfortoken', security=['AuthToken'])
    @token_auth.login_required
    async def get(self, request):
        """Exchange a valid auth token for the user details, perhaps an API_KEY if needed"""
        user = token_auth.current_user(request)
        if user:
            return {
                'user': user,
            }

    
@ns.route("/images")
class ImageUpload(Resource):
    async def post(self, request):
        # print(f"CONFIG PATH FOR IMAGE: {config.UPLOAD_DIR}")
        # if not os.path.exists(config.UPLOAD_DIR):
        #     os.makedirs(config.UPLOAD_DIR)

        # Ensure a file was sent
        upload_file = request.files.get('file')
        if not upload_file:
            return json({"error": "Missing file"}, status=400)

        # file_path = f"{config.UPLOAD_DIR}/{upload_file.name}"

        # await self.write_file(file_path, upload_file.body)
        file_id = await insert_file_stream(upload_file.name, upload_file.body)

        return json({'result': 'ok'})

    async def write_file(self, path, body):
        async with aiofiles.open(path, 'wb') as f:
            await f.write(body)
        f.close() 

@ns.route("/images/<filename>")
@ns.param('filename', "Image Filename", type="string", format="string")
class ImageDownload(Resource):
    async def get(self, request, *args, filename=None):
        if filename == None:
            return json({'error': 'Missing file name'}, status=404)

        # file_path = f"{config.UPLOAD_DIR}/{filename}"
        # if not os.path.isfile(file_path):
        #     return json({'error': f"{filename} can't be found"}, status=404)

        async def download_fn(response):
            await write_file_to_stream(filename, response)

        return response.stream(download_fn)
        # return await response.file_stream(file_path)

@ns.route('/annotations')
@ns.param('station_no', "Station Number", type="number", format="integer", _in="query")
@ns.response(404, 'Annotations not found')
class Annotations(Resource):
    accept_types = ["application/json"]

    @ns.doc('get_station_annotations', params=OrderedDict([
        ("property_filter", {
            "description": "Comma delimited list of properties to retrieve.\n\n"
                           "_Enter * for all_.",
            "required": False, "type": "string", "format": "text"}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, **kwargs):
        '''Get cosmoz station annotations.'''
        station_no = request.args.get('station_no', None)
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)

        get_annotations_func = partial(get_station_annotations_mongo, station_no)

        return await get_obj_reponse(request, self.accept_types, get_annotations_func, self.api)


    @ns.doc('post_annotation', security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    async def post(self, request, *args, **kwargs):
        '''Add new cosmoz station annotation.'''
        if not "annotation" in request.json:
            return text("annotation must be in the payload", status=400)
        
        return await generic_create_request(ANNOTATION_COLLECTION, 'annotation',  request.json["annotation"], AnnotationSchema)

@ns.route('/annotations/<a_id>')
@ns.param('a_id', "Annotation ID", type="string")
@ns.response(404, 'Annotation not found')
class Annotation(Resource):
    accept_types = ["application/json"]

    @ns.doc('get_annotation', params=OrderedDict([
        ("property_filter", {
            "description": "Comma delimited list of properties to retrieve.\n\n"
                           "_Enter * for all_.",
            "required": False, "type": "string", "format": "text"}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, a_id=None, **kwargs):
        '''Get cosmoz station calibrations.'''
        if a_id is None:
            raise RuntimeError("id is mandatory.")

        get_annotation_func = partial(get_annotation_mongo, a_id)

        return await get_obj_reponse(request, self.accept_types, get_annotation_func, self.api)

    @ns.doc('put_annotation', security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    async def put(self, request, *args, a_id=None, **kwargs):
        '''Update cosmoz station annotation'''
        if not "annotation" in request.json:
            text("annotation must be in the payload", status=400)

        return await generic_update_request(ANNOTATION_COLLECTION, a_id, 'annotation', request.json["annotation"], AnnotationSchema)
