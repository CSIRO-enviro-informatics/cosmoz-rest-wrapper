from collections import OrderedDict
import secrets
import bson
import oauth1_routes
import oauth2_routes
from pymongo import MongoClient
import config
from util import datetime_to_iso, datetime_from_iso
import datetime

########
# | apikey | access_token | access_token_secret | scopes | oauth_v | oauth_client | created | expires |
########

def get_apikey_mongo(apikey, params):
    client = MongoClient(config.MONGODB_HOST, config.MONGODB_PORT)  # 27017
    apikey = str(apikey)
    params = params or {}
    property_filter = params.get('property_filter', [])
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_filter = None
        else:
            select_filter = OrderedDict({v: True for v in property_filter})
            if "apikey" not in select_filter:
                select_filter['apikey'] = True
            if "_id" not in select_filter:
                select_filter['_id'] = False
            select_filter.move_to_end('_id', last=False)
    else:
        select_filter = None
    db = client.cosmoz
    api_keys_collection = db.api_keys
    row = api_keys_collection.find_one({'apikey': apikey}, projection=select_filter)
    if row is None or len(row) < 1:
        raise LookupError("Cannot find apikey.")
    resp = row
    if select_filter is None or select_filter.get('_id', False) is False:
        if '_id' in resp:
            del resp['_id']
    for k, v in resp.items():
        if isinstance(v, datetime.datetime):
            if v.tzinfo is None:
                resp[k] = v.replace(tzinfo=datetime.timezone.utc)
    return resp


def find_apikey_by_access_token_mongo(access_token, params):
    client = MongoClient(config.MONGODB_HOST, config.MONGODB_PORT)  # 27017
    access_token = str(access_token)
    params = params or {}
    property_filter = params.get('property_filter', [])
    if property_filter and len(property_filter) > 0:
        if '*' in property_filter:
            select_filter = None
        else:
            select_filter = OrderedDict({v: True for v in property_filter})
            if "apikey" not in select_filter:
                select_filter['apikey'] = True
            if "access_token" not in select_filter:
                select_filter['access_token'] = True
            if "_id" not in select_filter:
                select_filter['_id'] = False
            select_filter.move_to_end('_id', last=False)
    else:
        select_filter = None
    db = client.cosmoz
    api_keys_collection = db.api_keys
    row = api_keys_collection.find_one({'access_token': access_token}, projection=select_filter)
    if row is None or len(row) < 1:
        raise LookupError("Cannot find apikey with that access token.")
    resp = row
    if select_filter is None or select_filter.get('_id', False) is False:
        if '_id' in resp:
            del resp['_id']
    for k, v in resp.items():
        if isinstance(v, datetime.datetime):
            if v.tzinfo is None:
                resp[k] = v.replace(tzinfo=datetime.timezone.utc)
    return resp


def put_apikey_mongo(apikey, params, renew=False):
    client = MongoClient(config.MONGODB_HOST, config.MONGODB_PORT)  # 27017
    apikey = str(apikey)
    params = params or {}
    params['apikey'] = apikey
    criteria = {'apikey': apikey}
    if renew:
        assert 'access_token' in params
        criteria['access_token'] = params['access_token']
    db = client.cosmoz
    api_keys_collection = db.api_keys
    row = api_keys_collection.update_one(criteria, {"$set": params}, upsert=(not renew))
    if not row:
        raise LookupError("Cannot set apikey.")
    resp = params
    return resp


async def check_apikey_valid(apikey):
    params = {'property_filter': ['access_token', 'expires']}
    try:
        record = get_apikey_mongo(apikey, params)
    except LookupError as lu:
        return False, "Not Found"
    expires = record.get('expires', None)
    if expires is not None:
        if isinstance(expires, str):
            expires = datetime_from_iso(expires)
        now = datetime.datetime.now(datetime.timezone.utc)
        if expires < now:
            return False, "Expired"
    access_token = record.get('access_token', None)
    if access_token is None:
        return False, "No access token"
    return True, "OK"


async def test_apikey(apikey):
    params = {'property_filter': ['access_token', 'access_token_secret', 'oauth_v', 'oauth_client']}
    try:
        record = get_apikey_mongo(apikey, params)
    except LookupError as lu:
        return False, "Not Found"
    access_token = record.get('access_token', None)
    access_token_secret = record.get('access_token_secret', None)
    oauth_v = record.get('oauth_v', "")
    is_v1 = oauth_v in ("1", "1.1", "1.0a", 1)
    if access_token is None:
        raise RuntimeError("Cannot test API-Key, required credentials missing")
    if is_v1 and access_token_secret is None:
        raise RuntimeError("Cannot test API-Key, required credentials missing")
    oauth_client = record.get('oauth_client', None)
    if is_v1:
        works = await oauth1_routes.test_oauth1_token(oauth_client, access_token, access_token_secret)
    else:
        works = await oauth2_routes.test_oauth2_token(oauth_client, access_token)
    if not works:
        return False, "API-Key associated oauth access_token does not work. Perhaps it has been revoked."
    return True, "OK"


async def create_apikey_from_access_token(oauth_client, oauth_v, oauth_resp):
    if oauth_v in ("1", "1.1", "1.0a", 1):
        try:
            access_token = oauth_resp['oauth_token']
            access_token_secret = oauth_resp['oauth_token_secret']
        except AttributeError:
            raise RuntimeError("Access token and Secret were not received from the oauth1 provider.")
        scopes_or_realms = oauth_resp.get('oauth_authorized_realms', None)
    else:
        try:
            access_token = oauth_resp['access_token']
        except AttributeError:
            raise RuntimeError("Access token was not received from the oauth2 provider.")
        access_token_secret = ""
        scopes_or_realms = oauth_resp.get('scope')

    try:
        exists = find_apikey_by_access_token_mongo(access_token, None)
    except LookupError:
        exists = False
    if exists:
        apikey = exists['apikey']
        return await renew_apikey_from_access_token(oauth_client, oauth_v, apikey, oauth_resp)

    apikey = secrets.token_urlsafe(32)
    now = datetime.datetime.now(datetime.timezone.utc)
    params = {
        "access_token": access_token,
        "access_token_secret": access_token_secret,
        "scopes": scopes_or_realms,
        "oauth_v": oauth_v,
        "oauth_client": oauth_client,
        "created": now,
        "expires": now + datetime.timedelta(days=7)  # TODO, is 7 days right?
    }
    new_record = put_apikey_mongo(apikey, params, renew=False)
    return new_record['apikey']


async def renew_apikey_from_access_token(oauth_client, oauth_v, apikey, oauth_resp):
    if oauth_v in ("1", "1.1", "1.0a", 1):
        try:
            access_token = oauth_resp['oauth_token']
        except AttributeError:
            raise RuntimeError("Access token and Secret were not received from the oauth1 provider.")
    else:
        try:
            access_token = oauth_resp['access_token']
        except AttributeError:
            raise RuntimeError("Access token was not received from the oauth2 provider.")

    now = datetime.datetime.now(datetime.timezone.utc)
    params = {
        "access_token": access_token,
        "oauth_v": oauth_v,
        "oauth_client": oauth_client,
        "expires": now + datetime.timedelta(days=7)  # TODO, is 7 days right?
    }
    new_record = put_apikey_mongo(apikey, params, renew=True)
    return new_record['apikey']