import warnings

from beaker.cache import CacheManager
from beaker.session import Session, SessionObject
from beaker.util import coerce_session_params, parse_cache_config_options


class CacheApplicationWrapper(object):
    def __init__(self, handler, config):
        """Initialize Caching Support

        The Cache Application Wrapper will make a CacheManager instance available
        every request under the ``environ['beaker.cache']`` key and inside the
        TurboGears request context as ``cache``.

        ``config``
            dict  All settings should be prefixed by 'cache.'.
            For complete list of options refer to ``beaker`` documentation.

        """
        config = config or {}

        self.handler = handler
        self.options = parse_cache_config_options(config)
        self.cache_manager = CacheManager(**self.options)

    def __call__(self, controller, environ, context):
        environ['beaker.cache'] = context.cache = self.cache_manager

        if 'paste.testing_variables' in environ:
            environ['paste.testing_variables']['cache'] = context.cache

        return self.handler(controller, environ, context)


class SessionApplicationWrapper(object):
    def __init__(self, handler, config):
        """Initialize the Session Support

        The Session Application Wrapper will make a lazy session instance
        available every request under the ``environ['beaker.session']`` key and
        inside TurboGears context as ``session``.

        ``config``
            dict  All settings should be prefixed by 'session.'.
            For complete list of options refer to ``beaker`` documentation.

        """
        config = config or {}
        self.handler = handler

        # Load up the default params
        self.options = dict(invalidate_corrupt=True, type=None,
                            data_dir=None, key='beaker.session.id',
                            timeout=None, secret=None, log_file=None)

        # Pull out any config args meant for beaker session. if there are any
        for key, val in config.iteritems():
            if key.startswith('beaker.session.'):
                warnings.warn('Session options should start with session. '
                              'instead of baker.session.', DeprecationWarning, 2)
                self.options[key[15:]] = val
            elif key.startswith('session.'):
                self.options[key[8:]] = val

        # Coerce and validate session params
        coerce_session_params(self.options)

    def __call__(self, controller, environ, context):
        context.session = session = SessionObject(environ, **self.options)
        environ['beaker.session'] = session
        environ['beaker.get_session'] = self._get_session

        if 'paste.testing_variables' in environ:
            environ['paste.testing_variables']['session'] = session

        response = self.handler(controller, environ, context)

        if session.accessed():
            session.persist()
            if session.__dict__['_headers']['set_cookie']:
                cookie = session.__dict__['_headers']['cookie_out']
                if cookie:
                    response.headers.extend((('Set-cookie', cookie),))

        return response

    def _get_session(self):
        return Session({}, use_cookies=False, **self.options)
