# -*- coding: utf-8 -*-
#
import sys
module = sys.modules[__name__]
CONFIG = module.CONFIG = {}
INFLUXDB_HOST = CONFIG['INFLUX_HOST'] = "cosmoz.influxdb"
INFLUXDB_PORT = CONFIG['INFLUX_PORT'] = 8086
MONGODB_HOST = CONFIG['MONGODB_HOST'] = "cosmoz.mongodb"
MONGODB_PORT = CONFIG['MONGODB_PORT'] = 27017



