# -*- coding: utf-8 -*-
#
import sys
from util import load_env
from os import getenv
load_env()
module = sys.modules[__name__]
TRUTHS = {True, 1, '1', 'T', 't', 'true', 'TRUE', 'True'}
CONFIG = module.CONFIG = {}

OVERRIDE_SERVER_NAME = CONFIG['OVERRIDE_SERVER_NAME'] = getenv("SANIC_OVERRIDE_SERVER_NAME", "localhost:9001")
PROXY_ROUTE_BASE = CONFIG['PROXY_ROUTE_BASE'] = getenv("SANIC_PROXY_ROUTE_BASE", "")
SANIC_SERVER_NAME = CONFIG['SANIC_SERVER_NAME'] = getenv("SANIC_SERVER_NAME", "")
INFLUXDB_HOST = CONFIG['INFLUXDB_HOST'] = getenv("INFLUXDB_HOST", "cosmoz.influxdb")
INFLUXDB_PORT = CONFIG['INFLUXDB_PORT'] = int(getenv("INFLUXDB_PORT", 8086))
MONGODB_HOST = CONFIG['MONGODB_HOST'] = getenv("MONGODB_HOST", "cosmoz.mongodb")
MONGODB_PORT = CONFIG['MONGODB_PORT'] = int(getenv("MONGODB_PORT", 27017))
METRICS_DIRECTORY = CONFIG['METRICS_DIRECTORY'] = getenv("METRICS_DIRECTORY", ".")
DEBUG = CONFIG['DEBUG'] = getenv("SANIC_DEBUG", '') in TRUTHS



