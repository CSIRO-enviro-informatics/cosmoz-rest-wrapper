import sys
from collections import OrderedDict
import datetime
import pytz
from sanic_restplus import Api, Resource, fields
from sanic.response import json
from sanic.exceptions import ServiceUnavailable
from sanic_jinja2_spf import sanic_jinja2

from .functions import get_observations_influx, get_station_mongo, get_stations_mongo, get_last_observations_influx

is_py36 = sys.version_info[0:3] >= (3, 6, 0)

url_prefix = 'rest'

api = Api(title="CSIRO Cosmoz REST Interface",
          prefix=url_prefix, doc='/'.join([url_prefix, "doc"]),
          default_mediatype="application/json",
          additional_css="/static/material_swagger.css")
ns = api.default_namespace

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
    return None

@ns.route('/stations')
class Stations(Resource):
    '''Gets a JSON representation of all sites in the COSMOZ database.'''

    @ns.doc('get_stations', params=OrderedDict([
        # ("username", {"description": "Your Cosmoz SQL DB username.", "required": True,
        #               "type": "string", "format": "text"}),
        #
        # ("password", {"description": "Your Cosmoz SQL DB password.", "required": True,
        #                  "type": "string", "format": "password"}),
        ("property_filter", {"description": "Comma delimited list of properties to retrieve.\n\n"
                             "_Enter * for all_.",
                             "required": False, "type": "string", "format": "text"}),
        ("count", {"description": "Number of records to return.",
                   "required": False, "type": "number", "format": "integer", "default": 100}),
        ("offset", {"description": "Skip number of records before reading count.",
                    "required": False, "type": "number", "format": "integer", "default": 0}),
    ]))

    async def get(self, request, *args, **kwargs):
        '''Get cosmoz stations.'''
        username = request.args.getlist('username', None)
        password = request.args.getlist('password', None)
        if username:
            username = next(iter(username))
        if password:
            password = next(iter(password))
        property_filter = request.args.getlist('property_filter', None)
        if property_filter:
            property_filter = str(next(iter(property_filter))).split(',')
        count = request.args.getlist('count', None)
        if count:
            count = int(next(iter(count)))
        else:
            count = 1000
        offset = request.args.getlist('offset', None)
        if offset:
            offset = int(next(iter(offset)))
        else:
            offset = 0
        obs_params = {
            "username": username,
            "password": password,
            "property_filter": property_filter,
            "count": count,
            "offset": offset,
        }
        res = get_stations_mongo(obs_params)
        return json(res, status=200)

@ns.route('/stations/<station_no>')
@ns.param('station_no', "Station Number", type="number", format="integer")
@ns.response(404, 'Station not found')
class Station(Resource):
    accept_types = ["application/json", "application/csv", "text/plain"]
    '''Gets site date for station_no.'''

    @ns.doc('get_station', params=OrderedDict([
        # ("username", {"description": "Your Cosmoz SQL DB username.", "required": True,
        #               "type": "string", "format": "text"}),
        #
        # ("password", {"description": "Your Cosmoz SQL DB password.", "required": True,
        #                  "type": "string", "format": "password"}),
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
        username = request.args.getlist('username', None)
        if username:
            username = next(iter(username))
        password = request.args.getlist('password', None)
        if password:
            password = next(iter(password))
        return_type = match_accept_mediatypes_to_provides(request, self.accept_types)
        format = request.args.getlist('format', None)
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
            "username": username,
            "password": password,
            "property_filter": property_filter,
        }

        res = get_station_mongo(station_no, obs_params)
        if return_type == "application/json":
            return json(res, status=200)
        elif return_type == "applcation/csv":
            raise NotImplementedError()
            #return build_csv(res)
        elif return_type == "text/plain":
            headers = {'Content-Type': return_type}
            jinja2 = get_jinja2_for_api(self.api)
            if is_py36:
                return jinja2.render_async('site_data_txt.html', request, headers=headers, **res)
            else:
                return jinja2.render('site_data_txt.html', request, headers=headers, **res)

@ns.route('/stations/<station_no>/observations')
@ns.param('station_no', "Station Number", type="number", format="integer")
class Observations(Resource):
    '''Gets a JSON representation of observation records in the COSMOZ database.'''

    @ns.doc('get_records', params=OrderedDict([
        # ("username", {"description": "Your Cosmoz SQL DB username.", "required": True,
        #               "type": "string", "format": "text"}),
        #
        # ("password", {"description": "Your Cosmoz SQL DB password.", "required": True,
        #                  "type": "string", "format": "password"}),
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
                   "required": False, "type": "number", "format": "integer", "default": 1000}),
        ("offset", {"description": "Skip number of records before reading count.",
                    "required": False, "type": "number", "format": "integer", "default": 0}),
    ]))

    async def get(self, request, *args, station_no=None, **kwargs):
        '''Get cosmoz records.'''

        nowtime = datetime.datetime.now().replace(tzinfo=pytz.UTC)
        username = request.args.getlist('username', None)
        password = request.args.getlist('password', None)
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
        if username:
            username = next(iter(username))
        if password:
            password = next(iter(password))
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
        startdate = request.args.getlist('startdate', None)
        if startdate:
            startdate = next(iter(startdate))
        else:
            startdate = (nowtime + datetime.timedelta(days=-365))\
                .replace(hour=0, minute=0, second=0, microsecond=0)
        enddate = request.args.getlist('enddate', None)
        if enddate:
            enddate = next(iter(enddate))
        else:
            enddate = nowtime.replace(hour=23, minute=59, second=59, microsecond=0)
        count = request.args.getlist('count', None)
        if count:
            count = int(next(iter(count)))
        else:
            count = 1000
        offset = request.args.getlist('offset', None)
        if offset:
            offset = int(next(iter(offset)))
        else:
            offset = 0
        obs_params = {
            "processing_level": processing_level,
            "property_filter": property_filter,
            "username": username,
            "password": password,
            "aggregate": aggregate,
            "startdate": startdate,
            "enddate": enddate,
            "count": count,
            "offset": offset,
        }
        res = get_observations_influx(station_no, obs_params)
        return json(res, status=200)


@ns.route('/stations/<station_no>/lastobservations')
@ns.param('station_no', "Station Number", type="number", format="integer")
class LastObservations(Resource):
    '''Gets a JSON representation of recent observation records in the COSMOZ database.'''

    @ns.doc('get_records', params=OrderedDict([
        # ("username", {"description": "Your Cosmoz SQL DB username.", "required": True,
        #               "type": "string", "format": "text"}),
        #
        # ("password", {"description": "Your Cosmoz SQL DB password.", "required": True,
        #                  "type": "string", "format": "password"}),
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

        username = request.args.getlist('username', None)
        password = request.args.getlist('password', None)
        if station_no is None:
            raise RuntimeError("station_no is mandatory.")
        station_no = int(station_no)
        if username:
            username = next(iter(username))
        if password:
            password = next(iter(password))
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
            "username": username,
            "password": password,
            "count": count,
        }
        res = get_last_observations_influx(station_no, obs_params)
        return json(res, status=200)
