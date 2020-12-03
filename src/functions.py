import asyncio
import datetime
from collections import OrderedDict

import bson
from influxdb import InfluxDBClient
from motor.motor_asyncio import AsyncIOMotorClient as MotorClient
import config
from util import datetime_to_iso, datetime_from_iso, datetime_to_date_string

STATION_COLLECTION = 'all_stations'

persistent_clients = {
    'influx_client': None,
    'mongo_client': None
}

def get_mongo_client():
    if persistent_clients['mongo_client'] is None:
        persistent_clients['mongo_client'] = MotorClient(
            config.MONGODB_HOST, config.MONGODB_PORT,
            io_loop=asyncio.get_event_loop())
    return persistent_clients['mongo_client']

def get_influx_client():
    if persistent_clients['influx_client'] is None:
        persistent_clients['influx_client'] = InfluxDBClient(
            config.INFLUXDB_HOST, config.INFLUXDB_PORT, 'root', 'root',
            'cosmoz', timeout=30)
    return persistent_clients['influx_client']

obsv_variable_to_column_map = {
    'timestamp': 'Timestamp',
    'soil_moist': 'SoilMoist',
    'effective_depth': 'EffectiveDepth',
    'rainfall': 'Rainfall',
    'soil_moist_filtered': 'SoilMoistFiltered',
    'depth_filtered': 'DepthFiltered',
    ###
    'corr_count': 'CorrCount',
    'count': 'Count',
    'flag': 'Flag',
    'intensity_corr': 'IntensityCorr',
    'pressure_corr': 'PressureCorr',
    'wv_corr': 'WVCorr'
}

obsv_column_to_variable_map = { v: k for k,v in obsv_variable_to_column_map.items() }

station_variable_to_column_map = {
    'altitude': 'Altitude',
    'beta': 'Beta',
    'bulk_density': 'BulkDensity',
    'calibration_type': 'CalibrationType',
    'contact': 'Contact',
    'cutoff_rigidity': 'CutoffRigidity',
    'elev_scaling': 'ElevScaling',
    'email': 'Email',
    'installation_date': 'InstallationDate',
    'latit_scaling': 'LatitScaling',
    'latitude': 'Latitude',
    'lattice_water_g_g': 'LatticeWater_g_g',
    'longitude': 'Longitude',
    'n0_cal': 'N0_Cal',
    'nmdb': 'NMDB',
    'network': 'Network',
    'ref_intensity': 'RefIntensity',
    'ref_pressure': 'RefPressure',
    'sat_data_select': 'SatDataSelect',
    'scaling': 'Scaling',
    'site_description': 'SiteDescription',
    'site_name': 'SiteName',
    'site_no': 'SiteNo',
    'site_photo_name': 'SitePhotoName',
    'soil_organic_matter_g_g': 'SoilOrganicMatter_g_g',
    'timezone': 'Timezone',
    'tube_type': 'TubeType'
}

station_column_to_variable_map = { v: k for k,v in station_variable_to_column_map.items() }

async def get_station_mongo(station_number, params, json_safe=True, jinja_safe=False):
    mongo_client = get_mongo_client()
    station_number = int(station_number)
    params = params or {}
    property_filter = params.get('property_filter', [])
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_filter = None
        else:
            select_filter = OrderedDict({v: True for v in property_filter})
            if "site_no" not in select_filter:
                select_filter['site_no'] = True
            select_filter.move_to_end('site_no', last=False)
            if "_id" not in select_filter:
                select_filter['_id'] = False
            select_filter.move_to_end('_id', last=False)
    else:
        select_filter = None
    db = mongo_client.cosmoz
    all_stations_collection = db[STATION_COLLECTION]
    s = await mongo_client.start_session()
    try:
        count = await all_stations_collection.count_documents({})
        row = await all_stations_collection.find_one({'site_no': station_number}, projection=select_filter, session=s)
    finally:
        await s.end_session()
    if row is None or len(row) < 1:
        raise LookupError("Cannot find site.")
    resp = row
    #resp = { station_column_to_variable_map[c]: v for c,v in row.items() if c in station_column_to_variable_map.keys() }
    if select_filter is None or select_filter.get('_id', False) is False:
        if '_id' in resp:
            del resp['_id']
    if jinja_safe and 'status' in resp:
        resp['_status'] = resp['status']
        del resp['status']
    for r, v in resp.items():
        if isinstance(v, datetime.datetime):
            if (json_safe and json_safe != "orjson") or jinja_safe:  # orjson can handle native datetimes
                v = datetime_to_iso(v)
            resp[r] = v
        elif isinstance(v, bson.decimal128.Decimal128):
            g = v.to_decimal()
            if json_safe and g.is_nan():
                g = 'NaN'
            elif json_safe == "orjson":  # orjson can't do decimal
                g = float(g)  # converting to float is fine because Javascript numbers are native double-float anyway.
            resp[r] = g
    if json_safe and 'id' not in resp and 'site_no' in resp:
        resp['id'] = resp['site_no']
    resp = {
        'meta': {'total': count, },
        'station': resp,
    }
    return resp


async def get_station_calibration_mongo(station_number, params, json_safe=True, jinja_safe=False):
    mongo_client = get_mongo_client()
    station_number = int(station_number)
    params = params or {}
    property_filter = params.get('property_filter', [])
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_filter = None
        else:
            select_filter = OrderedDict({v: True for v in property_filter})
            if "site_no" not in select_filter:
                select_filter['site_no'] = True
            select_filter.move_to_end('site_no', last=False)
            if "_id" not in select_filter:
                select_filter['_id'] = False
            select_filter.move_to_end('_id', last=False)
    else:
        select_filter = None
    if select_filter is None:
        select_filter = {'_id': False}
    db = mongo_client.cosmoz
    stations_calibration_collection = db.stations_calibration
    s = await mongo_client.start_session()
    try:
        total = await stations_calibration_collection.count_documents({'site_no': station_number})
        cursor = stations_calibration_collection.find({'site_no': station_number}, projection=select_filter)
        if cursor is None:
            raise LookupError("Cannot find site calibration.")

        #resp = { station_column_to_variable_map[c]: v for c,v in row.items() if c in station_column_to_variable_map.keys() }
        # if 'installation_date' in resp:
        #     resp['installation_date'] = datetime_to_iso(resp['installation_date'])
        responses = []
        while (await cursor.fetch_next):
            resp = cursor.next_object()
            if "_id" in resp:
                del resp['id']
            for r, v in resp.items():
                if isinstance(v, datetime.datetime):
                    if (json_safe and json_safe != "orjson") or jinja_safe: # orjson can handle native datetimes
                        v = datetime_to_iso(v)
                    resp[r] = v
                elif isinstance(v, bson.decimal128.Decimal128):
                    g = v.to_decimal()
                    if json_safe and g.is_nan():
                        g = 'NaN'
                    elif json_safe == "orjson":  # orjson can't do decimal
                        g = float(g)  # converting to float is fine because Javascript numbers are native double-float anyway.
                    resp[r] = g

            responses.append(resp)
    finally:
        await s.end_session()
    count = len(responses)
    resp = {
        'meta': {
            'total': total,
            'count': count,
            'offset': 0,
        },
        'calibrations': responses,
    }
    return resp


async def get_stations_mongo(params, json_safe=True, jinja_safe=False):
    mongo_client = get_mongo_client()
    params = params or {}
    property_filter = params.get('property_filter', [])
    count = params.get('count', 1000)
    offset = params.get('offset', 0)
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_filter = None
        else:
            select_filter = OrderedDict({v: True for v in property_filter})
            if "site_no" not in select_filter:
                select_filter['site_no'] = True
            select_filter.move_to_end('site_no', last=False)
            if "_id" not in select_filter:
                select_filter['_id'] = False
            select_filter.move_to_end('_id', last=False)
    else:
        select_filter = None

    db = mongo_client.cosmoz
    all_stations_collection = db[STATION_COLLECTION]
    s = await mongo_client.start_session()
    try:
        total_stations = await all_stations_collection.count_documents({})
        all_stations_cur = all_stations_collection.find({}, projection=select_filter, skip=offset, limit=count, session=s)
        if all_stations_cur is None:
            raise LookupError("Cannot find any sites.")
        count = 0
        stations = []
        while (await all_stations_cur.fetch_next):
            station = all_stations_cur.next_object()
            #station = { station_column_to_variable_map[c]: v
            #            for c,v in _row.items() if c in station_column_to_variable_map.keys() }
            if jinja_safe and 'status' in station:
                station['_status'] = station['status']
                del station['status']
            for r, v in station.items():
                if isinstance(v, datetime.datetime):
                    if (json_safe and json_safe != "orjson") or jinja_safe: #orjson can handle native datetimes
                        v = datetime_to_iso(v)
                    station[r] = v
                elif isinstance(v, bson.decimal128.Decimal128):
                    g = v.to_decimal()
                    if json_safe and g.is_nan():
                        g = 'NaN'
                    elif json_safe == "orjson":  # orjson can't do decimal
                        g = float(g)  # converting to float is fine because Javascript numbers are native double-float anyway.
                    station[r] = g
            if select_filter is None or select_filter.get('_id', False) is False:
                if '_id' in station:
                    del station['_id']
            if json_safe and 'id' not in station and 'site_no' in station:
                station['id'] = station['site_no']
            stations.append(station)
            count += 1
    finally:
        await s.end_session()
    resp = {
        'meta': {
            'total': total_stations,
            'count': count,
            'offset': offset,
        },
        'stations': stations,
    }
    return resp

def get_last_observations_influx(site_number, params, json_safe=True, excel_safe=False):
    influx_client = get_influx_client()
    site_number = int(site_number)
    params = params or {}
    processing_level = params.get('processing_level', 3)
    property_filter = params.get('property_filter', [])
    count = params.get('count', 1)

    assert 0 <= processing_level <= 4, "Only levels 0, 1, 2, 3, 4 are acceptable."
    if processing_level < 1:
        db_measurement = "raw_values"
    else:
        db_measurement = "level{:d}".format(processing_level)

    all_rows = None
    get_all = "*"
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_string = get_all
        else:
            select_cols = property_filter
            if "time" not in select_cols:
                select_cols.insert(0, "time")
            select_string = ",".join(select_cols)
    else:
        select_string = get_all
    sql = 'SELECT {:s} FROM "{:s}" WHERE "site_no"=\'{:d}\' ORDER BY "time" DESC LIMIT {:d};' \
          .format(select_string, db_measurement, site_number, count)
    result = influx_client.query(sql)
    points = result.get_points()
    count = 0
    observations = []
    for _row in points:
        observation = _row
        if 'time' in observation and excel_safe:
            # hack to very quickly convert iso 8601 to yyyy-MM-dd hh:mm:ss for excel
            dt = observation['time'].replace('T', ' ')[:19]
            observation['time'] = dt
        #observation = {obsv_column_to_variable_map[c]: v
        #               for c, v in _row.items() if c in obsv_column_to_variable_map.keys()}
        #if 'time' in observation:
        #    observation['time'] = datetime_to_iso(observation['timestamp'])
        observations.append(observation)
        count = count+1
    resp = {
        'meta': {
        'site_no': site_number,
        'processing_level': processing_level,
        'count': count,
        #'start_date': datetime_to_iso(startdate) if startdate else '',
        #'end_date': datetime_to_iso(enddate) if enddate else '',
        },
        'observations': observations,
    }
    return resp

def get_observations_influx(site_number, params, json_safe=True, excel_safe=False):
    influx_client = get_influx_client()
    site_number = int(site_number)
    params = params or {}
    processing_level = params.get('processing_level', 3)
    property_filter = params.get('property_filter', [])
    count = params.get('count', 2000)
    offset = params.get('offset', 0)
    aggregate = params.get('aggregate', None)
    if aggregate == "" or aggregate == 0:
        aggregate = None
    startdate = params.get('startdate', None)
    enddate = params.get('enddate', None)
    if startdate is not None and isinstance(startdate, str):
        startdate = datetime_from_iso(startdate)
    if enddate is not None and isinstance(enddate, str):
        enddate = datetime_from_iso(enddate)

    assert 0 <= processing_level <= 4, "Only levels 0, 1, 2, 3 or 4 are acceptable."
    if processing_level < 1:
        db_measurement = "raw_values"
    else:
        db_measurement = "level{:d}".format(processing_level)

    all_rows = None
    if startdate is None:
        since_query = ""
    else:
        if isinstance(startdate, datetime.datetime):
            start_datetime_string = startdate.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        elif isinstance(startdate, str):
            start_datetime_string = startdate
        else:
            raise RuntimeError()
        since_query = " AND time >= \'{:s}\' ".format(start_datetime_string)

    if enddate is None:
        before_query = ""
    else:
        if isinstance(enddate, datetime.datetime):
            end_datetime_string = enddate.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        elif isinstance(enddate, str):
            end_datetime_string = enddate
        else:
            raise RuntimeError()
        before_query = " AND time <= \'{:s}\' ".format(end_datetime_string)

    if aggregate:
        get_all = "MEAN(*),MIN(*),MAX(*),COUNT(*)"
    else:
        get_all = "*"
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_string = get_all
        else:
            if aggregate:
                select_cols = ["MEAN({v:s}),MIN({v:s}),MAX({v:s}),COUNT({v:s})".format(v=v) for v in property_filter]
            else:
                select_cols = property_filter
            if "time" not in select_cols:
                select_cols.insert(0, "time")
            select_string = ",".join(select_cols)
    else:
        select_string = get_all
    if aggregate:
        sql = 'SELECT {:s} FROM "{:s}" WHERE "site_no"=\'{:d}\'{:s}{:s}GROUP BY time({:s}) ORDER BY "time" ASC LIMIT {:d} OFFSET {:d}; ' \
              .format(select_string, db_measurement, site_number, since_query, before_query, aggregate, count, offset)
    else:
        sql = 'SELECT {:s} FROM "{:s}" WHERE "site_no"=\'{:d}\'{:s}{:s}ORDER BY "time" ASC LIMIT {:d} OFFSET {:d}; ' \
              .format(select_string, db_measurement, site_number, since_query, before_query, count, offset)
    result = influx_client.query(sql)
    points = result.get_points()
    count = 0
    observations = []
    for _row in points:
        observation = _row
        if 'time' in observation and excel_safe:
            # hack to very quickly convert iso 8601 to yyyy-MM-dd hh:mm:ss for excel
            dt = observation['time'].replace('T', ' ')[:19]
            observation['time'] = dt
        #observation = {obsv_column_to_variable_map[c]: v
        #               for c, v in _row.items() if c in obsv_column_to_variable_map.keys()}
        #if 'time' in observation:
        #    observation['time'] = datetime_to_iso(observation['timestamp'])
        observations.append(observation)
        count = count+1
    if json_safe and json_safe != 'orjson':
        startdate = datetime_to_iso(startdate) if startdate else ''
        enddate = datetime_to_iso(enddate) if enddate else '',
    resp = {
        'meta': {
        'site_no': site_number,
        'processing_level': processing_level,
        'count': count,
        'offset': offset,
        'start_date': startdate,
        'end_date': enddate
        },
        'observations': observations,
    }
    if aggregate:
        resp['meta']['aggregation'] = str(aggregate)
    return resp

async def is_unique_val(collection, field, val):
    mongo_client = get_mongo_client()
    db = mongo_client.cosmoz
    c = db[collection]
    query = {}
    query[field] = val
    result = await c.find_one(query)
    return not result
    
async def insert(collection, val): 
    mongo_client = get_mongo_client()
    db = mongo_client.cosmoz
    c = db[collection]
    result = await c.insert_one(val)
    return result.inserted_id



