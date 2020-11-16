from functools import wraps
from sanic_httpauth import HTTPTokenAuth, get_request
import asyncio
from oauth2_routes import get_profile
import functions

#token_auth is defined below... python needs predeclaration of classes (hrmph)

USER_FIELD = 'user'

# a version of the httpTokenAuth that stores the result of the verify call into a 'user' variable on request
# more in line with how the flask version does it.
# also making it async aware
class HTTPTokenAuthWithUser(HTTPTokenAuth):
    def login_required(self, f):
        @wraps(f)
        async def decorated(*args, **kwargs):
            request = get_request(*args, **kwargs)

            auth = self.get_auth(request)
            request["authorization"] = auth

            # Sanic-CORS normally handles OPTIONS requests on its own, but in the
            # case it is configured to forward those to the application, we
            # need to ignore authentication headers and let the request through
            # to avoid unwanted interactions with CORS.
            if request.method != "OPTIONS":  # pragma: no cover
                password = self.get_auth_password(auth)
                user = await self.authenticate(request, auth, password)
                if not user:
                    return self.auth_error_callback(request)
                request[USER_FIELD] = user

            # If i make decorated async, can it be called sync? or do I need to
            # define a second function 
            if asyncio.iscoroutinefunction(f):
                return await f(*args, **kwargs)
            else: 
                return f(*args, **kwargs)

        return decorated

    async def authenticate(self, request, auth, stored_password):
        if auth:
            token = auth["token"]
        else:
            token = ""
        if self.verify_token_callback:
            if asyncio.iscoroutinefunction(self.verify_token_callback):
                return await self.verify_token_callback(token)
            else:
                return self.verify_token_callback(token)
        return False

    def current_user(self, request):
        if USER_FIELD in request:
            return request[USER_FIELD]
        return None

token_auth = HTTPTokenAuthWithUser(scheme='Bearer')

@token_auth.verify_token
async def verify_token(token):
    # Currently this is an oauth2 token from csiro_ldap oauth2 server
    # could be an API_KEY in future, or we could have another HTTPTokenAuthWithUser for api_key headers
    profile = await get_profile(None, token)

    if profile and await is_admin(profile['id']):
        return {
            "id": profile['id'],
            "displayName": profile['displayName'],
            "email": profile['email']
            # "apiKey": ...
        }

async def is_admin(ident):
    #hard codes
    if ident.lower() in ['sea066', 'som05d', 'mcj002', 'ste652']:
        return True

    #else check the DB
    mongo_client = functions.get_mongo_client()
    db = mongo_client.cosmoz
    users = db.users
    user = await users.find_one({'ident': ident, 'role': 'admin'})    
    if user:
        return True
    return False

