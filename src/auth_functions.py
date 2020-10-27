from functools import wraps
from sanic_httpauth import HTTPTokenAuth, get_request

# a version of the httpTokenAuth that stores the result of the verify call into a 'user' variable on request
# more in line with how the flask version does it.
USER_FIELD = 'user'

class HTTPTokenAuthWithUser(HTTPTokenAuth):
    def login_required(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            request = get_request(*args, **kwargs)

            auth = self.get_auth(request)
            request["authorization"] = auth

            # Sanic-CORS normally handles OPTIONS requests on its own, but in the
            # case it is configured to forward those to the application, we
            # need to ignore authentication headers and let the request through
            # to avoid unwanted interactions with CORS.
            if request.method != "OPTIONS":  # pragma: no cover
                password = self.get_auth_password(auth)
                user = self.authenticate(request, auth, password)
                if not user:
                    return self.auth_error_callback(request)
                request[USER_FIELD] = user

            return f(*args, **kwargs)

        return decorated

    def current_user(self, request):
        if USER_FIELD in request:
            return request[USER_FIELD]
        return None