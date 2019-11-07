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
import sys
from collections import OrderedDict
import datetime
from datetime import datetime, timezone, timedelta
from sanic_restplus import Api, Resource, fields
from sanic.response import json, text
from sanic.exceptions import ServiceUnavailable
from sanic_jinja2_spf import sanic_jinja2

from functions import get_observations_influx, get_station_mongo, get_stations_mongo, get_station_calibration_mongo, get_last_observations_influx
from util import PY_36


url_prefix = 'rest'

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
    }
}

api = Api(title="CSIRO Cosmoz REST Interface",
          prefix=url_prefix, doc='/'.join([url_prefix, "doc"]),
          authorizations=security_defs,
          default_mediatype="application/json",
          additional_css="/static/material_swagger.css")
ns = api.default_namespace

MAX_RETURN_COUNT = 2147483647  # Highest 32bit signed int
EARLIEST_DATETIME = datetime.min.replace(year=1900, tzinfo=timezone.utc)

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
        profiles = request.headers['Accept'].split(',')
        # remove \s
        profiles = [x.replace(' ', '').strip() for x in profiles]

        # split off any weights and sort by them with default weight = 1
        profiles = [(float(x.split(';')[1].replace('q=', '')) if ";q=" in x else 1, x.split(';')[0]) for x in profiles]

        # sort profiles by weight, heaviest first
        profiles.sort(reverse=True)

        return [x[1] for x in profiles]
    except Exception as e:
        raise RuntimeError('You have requested a Media Type using an Accept header that is incorrectly formatted.')

def get_accept_profiles_in_order(request):
    """
    Reads an Accept-Profile HTTP header and returns an array of Profile URIs in descending weighted order

    :return: List of URIs of accept profiles in descending request order
    :rtype: list
    """
    try:
        # split the header into individual URIs, with weights still attached
        profiles = request.headers['Accept-Profile'].split(',')
        # remove <, >, and \s
        profiles = [x.replace('<', '').replace('>', '').replace(' ', '').strip() for x in profiles]

        # split off any weights and sort by them with default weight = 1
        profiles = [(float(x.split(';')[1].replace('q=', '')) if ";q=" in x else 1, x.split(';')[0]) for x in profiles]

        # sort profiles by weight, heaviest first
        profiles.sort(reverse=True)

        return [x[1] for x in profiles]
    except Exception as e:
        raise RuntimeError('You have requested a profile using an Accept-Profile header that is incorrectly formatted.')

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

@ns.route('/stations')
class Stations(Resource):
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

    async def get(self, request, *args, **kwargs):
        '''Get cosmoz stations.'''
        property_filter = request.args.getlist('property_filter', None)
        if property_filter:
            property_filter = str(next(iter(property_filter))).split(',')
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
        res = get_stations_mongo(obs_params)
        return json(res, status=200)

    @ns.doc('post_station', params=OrderedDict([
        ("name", {"description": "Station Name",
          "required": True, "type": "string", "format": "text"}),
        ("latitude", {"description": "Latitude (in decimal degrees)",
                  "required": True, "type": "string", "format": "number"}),
        ("longitude", {"description": "Longitude (in decimal degrees)",
                      "required": True, "type": "string", "format": "number"}),
    ]), security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    @ns.produces(["application/json"])
    async def post(self, request, *args, **kwargs):
        '''Add new cosmoz station.'''
        #Generates station number
        return text("OK")

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
        return_type = match_accept_mediatypes_to_provides(request, self.accept_types)
        format = request.args.getlist('format', None)
        if not format:
            format = request.args.getlist('_format', None)
        if format:
            format = next(iter(format))
            if format in self.accept_types:
                return_type = format
        if return_type is None:
            return ServiceUnavailable("Please use a valid accept type.")
        if return_type == "application/json":
            property_filter = request.args.getlist('property_filter', None)
            if property_filter:
                property_filter = str(next(iter(property_filter))).split(',')
        else:
            # CSV and TXT get all properties, regardless of property_filter
            property_filter = "*"
        obs_params = {
            "property_filter": property_filter,
        }
        json_safe = return_type == "application/json"
        res = get_station_mongo(station_no, obs_params, json_safe=json_safe)
        if return_type == "application/json":
            return json(res, status=200)
        elif return_type == "applcation/csv":
            raise NotImplementedError()
            #return build_csv(res)
        elif return_type == "text/plain":
            headers = {'Content-Type': return_type}
            jinja2 = get_jinja2_for_api(self.api)
            if PY_36:
                return jinja2.render_async('site_values_txt.html', request, headers=headers, **res)
            else:
                return jinja2.render('site_values_txt.html', request, headers=headers, **res)

    @ns.doc('put_station', params=OrderedDict([
        ("name", {"description": "Station Name",
          "required": True, "type": "string", "format": "text"}),
    ]), security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    @ns.produces(accept_types)
    async def put(self, request, *args, station_no=None, **kwargs):
        '''Add cosmoz station with station_no.'''
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        return text("OK")

@ns.route('/stations/<station_no>/calibration')
@ns.param('station_no', "Station Number", type="number", format="integer")
@ns.response(404, 'Station Calibration not found')
class StationCalibration(Resource):
    accept_types = ["application/json", "text/csv", "text/plain"]
    '''Gets site date for station_no.'''

    @ns.doc('get_station_cal', params=OrderedDict([
        ("property_filter", {
            "description": "Comma delimited list of properties to retrieve.\n\n"
                           "_Enter * for all_.",
            "required": False, "type": "string", "format": "text"}),
    ]))
    @ns.produces(accept_types)
    async def get(self, request, *args, station_no=None, **kwargs):
        '''Get cosmoz station calibrations.'''
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
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
            return ServiceUnavailable("Please use a valid accept type.")
        if return_type == "application/json":
            property_filter = request.args.getlist('property_filter', None)
            if property_filter:
                property_filter = str(next(iter(property_filter))).split(
                    ',')
        else:
            # CSV and TXT get all properties, regardless of property_filter
            property_filter = "*"
        obs_params = {
            "property_filter": property_filter,
        }
        json_safe = return_type == "application/json"
        res = get_station_calibration_mongo(station_no, obs_params, json_safe)
        if return_type == "application/json":
            return json(res, status=200)
        headers = {'Content-Type': return_type}
        jinja2 = get_jinja2_for_api(self.api)
        if return_type == "text/csv":
            if PY_36:
                return jinja2.render_async('site_data_cal_csv.html', request,
                                           headers=headers, **res)
            else:
                return jinja2.render('site_data_cal_csv.html', request,
                                     headers=headers, **res)
        elif return_type == "text/plain":
            if PY_36:
                return jinja2.render_async('site_data_cal_txt.html', request,
                                           headers=headers, **res)
            else:
                return jinja2.render('site_data_cal_txt.html', request,
                                     headers=headers, **res)

    @ns.doc('put_station_cal', params=OrderedDict([
        ("name", {"description": "Station Name",
          "required": True, "type": "string", "format": "text"}),
    ]), security={"APIKeyQueryParam": [], "APIKeyHeader": []})
    @ns.produces(accept_types)
    async def put(self, request, *args, station_no=None, **kwargs):
        '''Add cosmoz station calibration with station_no.'''
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        return text("OK")


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
        property_filter = request.args.getlist('property_filter', None)
        if property_filter:
            property_filter = str(next(iter(property_filter))).split(',')
        aggregate = request.args.getlist('aggregate', None)
        if aggregate:
            aggregate = str(next(iter(aggregate)))
        nowtime = datetime.utcnow().astimezone(timezone.utc)
        startdate = request.args.getlist('startdate', None)
        if startdate:
            startdate = next(iter(startdate))
        else:
            if return_type == "application/json":
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
        if return_type == "application/json":
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
        json_safe = return_type == "application/json"
        res = get_observations_influx(station_no, obs_params, json_safe)
        if return_type == "application/json":
            return json(res, status=200)
        headers = {'Content-Type': return_type}
        jinja2 = get_jinja2_for_api(self.api)
        if return_type == "text/csv":
            if processing_level == 0:
                template = "raw_data_csv.html"
            else:
                template = "level{}_data_csv.html".format(processing_level)
            if PY_36:
                return jinja2.render_async(template, request,
                                           headers=headers, **res)
            else:
                return jinja2.render(template, request, headers=headers, **res)
        elif return_type == "text/plain":
            headers = {'Content-Type': return_type}
            if processing_level == 0:
                template = "raw_data_txt.html"
            else:
                template = "level{}_data_txt.html".format(processing_level)
            if PY_36:
                return jinja2.render_async(template, request,
                                           headers=headers, **res)
            else:
                return jinja2.render(template, request, headers=headers, **res)


@ns.route('/stations/<station_no>/lastobservations')
@ns.param('station_no', "Station Number", type="number", format="integer")
class LastObservations(Resource):
    '''Gets a JSON representation of recent observation records in the COSMOZ database.'''

    @ns.doc('get_records', params=OrderedDict([
        ("processing_level", {"description": "Query the table for this processing level.\n\n"
                              "(0, 1, 2, 3, or 4).",
                              "required": False, "type": "number", "format": "integer", "default": 4}),
        ("property_filter", {"description": "Comma delimited list of properties to retrieve.\n\n"
                             "_Enter * for all_.",
                             "required": False, "type": "string", "format": "text"}),
        ("count", {"description": "Number of records to return.",
                   "required": False, "type": "number", "format": "integer", "default": 1}),
    ]))

    async def get(self, request, *args, station_no=None, **kwargs):
        '''Get recent cosmoz records.'''
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
        processing_level = request.args.getlist('processing_level', None)
        if processing_level:
            processing_level = int(next(iter(processing_level)))
        else:
            processing_level = 4
        property_filter = request.args.getlist('property_filter', None)
        if property_filter:
            property_filter = str(next(iter(property_filter))).split(',')
        count = request.args.getlist('count', None)
        if count:
            count = int(next(iter(count)))
        else:
            count = 1000
        obs_params = {
            "processing_level": processing_level,
            "property_filter": property_filter,
            "count": count,
        }
        res = get_last_observations_influx(station_no, obs_params)
        return json(res, status=200)
