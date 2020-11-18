from marshmallow import Schema, fields, validate, ValidationError
import itertools

class StationSchema(Schema):
    site_no = fields.Int(required=True)
    site_name = fields.Str(required=True, validate=validate.Length(min=1))
    tube_type = fields.Str()
    network = fields.Str()
    imei = fields.Str()
    sat_data_select = fields.Str()
    hydroinnova_serial_no = fields.Str()
    latitude = fields.Float(validate=validate.Range(-90,90))
    longitude = fields.Float(validate=validate.Range(-180,180))
    altitude = fields.Float(validate=validate.Range(0))
    installation_date = fields.Date()
    contact = fields.Str()
    email = fields.Email()
    site_description = fields.Str()
    calibration_type = fields.Str()
    timezone = fields.Str()
    site_photo_name = fields.Str()
    status = fields.Str()
    ref_pressure = fields.Str()
    ref_intensity = fields.Str()
    cutoff_rigidity = fields.Str()
    elev_scaling = fields.Str()
    latit_scaling = fields.Str()
    scaling = fields.Str()
    beta = fields.Str()
    n0_cal = fields.Str()
    bulk_density = fields.Str()
    lattice_water_g_g = fields.Str()
    soil_organic_matter_g_g = fields.Str()
    nmdb = fields.Str()

