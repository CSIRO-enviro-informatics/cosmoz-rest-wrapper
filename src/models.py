from marshmallow import Schema, fields, validate, ValidationError
import itertools

class StationSchema(Schema):
    site_no = fields.Int(required=True)
    site_name = fields.Str(required=True, validate=validate.Length(min=1))
    tube_type = fields.Str(required=True)
    network = fields.Str(required=True)
    imei = fields.Str()
    sat_data_select = fields.Str(required=True)
    latitude = fields.Float(required=True, validate=validate.Range(-90,90))
    longitude = fields.Float(required=True, validate=validate.Range(-180,180))
    altitude = fields.Float(required=True, validate=validate.Range(0))
    installation_date = fields.DateTime(required=True)
    site_description = fields.Str(required=True)
    calibration_type = fields.Str(required=True)
    timezone = fields.Str(required=True)
    site_photo_name = fields.Str(required=True)
    ref_pressure = fields.Float(required=True)
    ref_intensity = fields.Float(required=True)
    cutoff_rigidity = fields.Float(required=True)
    elev_scaling = fields.Float(required=True)
    latit_scaling = fields.Float(required=True)
    scaling = fields.Float(required=True)
    beta = fields.Float(required=True)
    n0_cal = fields.Float(required=True)
    bulk_density = fields.Float(required=True)
    lattice_water_g_g = fields.Float(required=True)
    soil_organic_matter_g_g = fields.Float(required=True)
    nmdb = fields.Str(required=True)
    hydroinnova_serial_no = fields.Str()
    contact = fields.Str()
    email = fields.Email()
    status = fields.Str()

class ObservationSchema(Schema):
    pass

class CalibrationSchema(Schema):
  id = fields.Str(required=False)
  site_no = fields.Int(required=True)
  date = fields.DateTime(required=True)
  label = fields.Str(required=True)
  loc = fields.Str(required=True)
  depth = fields.Str(required=True)
  vol = fields.Str(required=True)
  total_wet = fields.Float(required=True)
  total_dry = fields.Float(required=True)
  tare = fields.Float(required=True)
  soil_wet = fields.Float(required=True)
  soil_dry = fields.Float(required=True)
  gwc = fields.Float(required=True)
  bd = fields.Float(required=True)
  vwc = fields.Float(required=True)
