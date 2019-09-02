from os import path
from pickle import Pickler, Unpickler

from sanic_session.base import BaseSessionInterface
from sanic_session.utils import ExpiringDict


class FilesystemSessionInterface(BaseSessionInterface):
    def __init__(
        self,
        domain: str = None,
        expiry: int = 2592000,
        httponly: bool = True,
        cookie_name: str = "session",
        prefix: str = "session:",
        sessioncookie: bool = False,
        samesite: str = None,
        session_name="session",
        secure: bool = False,
        directory: str = None,
        filename: str = None
    ):

        super().__init__(
            expiry=expiry,
            prefix=prefix,
            cookie_name=cookie_name,
            domain=domain,
            httponly=httponly,
            sessioncookie=sessioncookie,
            samesite=samesite,
            session_name=session_name,
            secure=secure,
        )
        if directory is None:
            directory = path.curdir
        if filename is None:
            filename = "sessionstore.pickle"
        self._fss_filename = path.join(directory, filename)
        try:
            _cache = self._fss_unpickler()
        except FileNotFoundError:
            _cache = ExpiringDict()
            self._fss_pickler(_cache)

    def _fss_pickler(self, obj):
        with open(self._fss_filename, 'wb') as f:
            p = Pickler(f, 4)
            p.dump(obj)

    def _fss_unpickler(self):
        with open(self._fss_filename, 'rb') as f:
            p = Unpickler(f)
            return p.load()

    async def _get_value(self, prefix, sid):
        cache = self._fss_unpickler()
        return cache.get(self.prefix + sid)

    async def _delete_key(self, key):
        cache = self._fss_unpickler()
        if key in cache:
            cache.delete(key)
            self._fss_pickler(cache)

    async def _set_value(self, key, data):
        _cache = self._fss_unpickler()
        _cache.set(key, data, self.expiry)
        self._fss_pickler(_cache)


class FileSystemCache(object):
    __slots__ = ("_fsc_filename", "_fsc_threshold")

    def __init__(self, directory, filename=None, threshold=1000):
        self._fsc_threshold = threshold
        if directory is None:
            directory = path.curdir
        if filename is None:
            filename = "sanic_oauth_cache.pickle"
        self._fsc_filename = path.join(directory, filename)
        try:
            _cache = self._fss_unpickler()
        except FileNotFoundError:
            _cache = dict()
            _cache['_fsc_key_list'] = list()
            self._fss_pickler(_cache)

    def _fsc_pickler(self, obj):
        with open(self._fsc_filename, 'wb') as f:
            p = Pickler(f, 4)
            p.dump(obj)

    def _fsc_unpickler(self):
        with open(self._fsc_filename, 'rb') as f:
            p = Unpickler(f)
            return p.load()

    def __getattr__(self, key):
        try:
            return object.__getattribute__(self, key)
        except AttributeError:
            _cache = self._fsc_unpickler()
            _fsc_key_list = _cache.get('_fsc_key_list')
            try:
                obj = self._cache[key]
                if _fsc_key_list.index(key) < len(_fsc_key_list) - 1:
                    _fsc_key_list.remove(key)
                    _fsc_key_list.append(key)
                    _cache['_fsc_key_list'] = _fsc_key_list
                    self._fsc_pickler(_cache)
                return obj
            except KeyError:
                raise AttributeError(key)

    def __setattr__(self, key, value):
        try:
            object.__setattr__(self, key, value)
        except (AttributeError, ValueError):
            _cache = self._fsc_unpickler()
            _fsc_key_list = _cache.get('_fsc_key_list')
            try:
                _fsc_key_list.remove(key)
            except ValueError:
                pass
            _cache[key] = value
            _fsc_key_list.append(key)
            self._adj_threshold(_cache)
            self._fsc_pickler(_cache)
        return

    def _adj_threshold(self, _cache):
        _fsc_key_list = _cache.get('_fsc_key_list')
        while len(_fsc_key_list) > self._fsc_threshold:
            first_key = _fsc_key_list.pop(0)
            _cache.__delitem__(first_key)
        _cache['_fsc_key_list'] = _fsc_key_list
