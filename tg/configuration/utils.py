import inspect
import copy
from collections import deque
from .milestones import config_ready


class TGConfigError(Exception):pass


def coerce_config(configuration, prefix, converters):
    """Convert configuration values to expected types."""

    options = dict((key[len(prefix):], configuration[key])
                    for key in configuration if key.startswith(prefix))

    for option, converter in converters.items():
        if option in options:
            options[option] = converter(options[option])

    return options


def get_partial_dict(prefix, dictionary, container_type=dict):
    """Given a dictionary and a prefix, return a Bunch, with just items
    that start with prefix

    The returned dictionary will have 'prefix.' stripped so::

        get_partial_dict('prefix', {'prefix.xyz':1, 'prefix.zyx':2, 'xy':3})

    would return::

        {'xyz':1,'zyx':2}
    """

    match = prefix
    if not match.endswith('.'):
        match += "."
    n = len(match)

    new_dict = container_type(((key[n:], dictionary[key])
                                for key in dictionary
                                if key.startswith(match)))
    if new_dict:
        return new_dict
    else:
        raise AttributeError


class GlobalConfigurable(object):
    """Defines a configurable TurboGears object with a global default instance.

    GlobalConfigurable are objects which the user can create multiple instances to use
    in its own application or third party module, but for which TurboGears provides
    a default instance.

    Common examples are ``tg.flash`` and the default JSON encoder for which
    TurboGears provides default instances of ``.TGFlash`` and ``.JSONEncoder`` classes
    but users can create their own.

    While user created versions are configured calling the :meth:`.GlobalConfigurable.configure`
    method, global versions are configured by :class:`.AppConfig` which configures them when
    ``config_ready`` milestone is reached.

    """
    CONFIG_NAMESPACE = None
    CONFIG_OPTIONS = {}

    def configure(self, **options):
        """Expected to be implemented by each object to proceed with actualy configuration.

        Configure method will receive all the options whose name starts with ``CONFIG_NAMESPACE``
        (example ``json.isodates`` has ``json.`` namespace).

        If ``CONFIG_OPTIONS`` is specified options values will be converted with
        :func:`coerce_config` passing ``CONFIG_OPTIONS`` as the ``converters`` dictionary.

        """
        raise NotImplementedError('GlobalConfigurable objects must implement a configure method')

    @classmethod
    def create_global(cls):
        """Creates a global instance which configuration will be bound to :class:`.AppConfig`."""
        if cls.CONFIG_NAMESPACE is None:
            raise TGConfigError('Must specify a CONFIG_NAMESPACE attribute in class for the'
                                'namespace used by all configuration options.')

        obj = cls()
        config_ready.register(obj._load_config, persist_on_reset=True)
        return obj

    def _load_config(self):
        from tg.configuration import config
        self.configure(**coerce_config(config, self.CONFIG_NAMESPACE,  self.CONFIG_OPTIONS))


class ConfigurationFeature(object):
    """Defines a configuration step for Application Configurator :class:`.AppConfig`"""
    CONFIG_NAMESPACE = None
    CONFIG_OPTIONS = {}
    CONFIG_DEFAULTS = {}

    def __init__(self, config):
        if self.CONFIG_NAMESPACE is None or self.CONFIG_NAMESPACE[-1] != '.':
            raise TGConfigError('Configuration Features must have a namespace '
                                'in the form: "namespace."')

        for name, default_value in self.CONFIG_DEFAULTS.items():
            config[self.CONFIG_NAMESPACE + name] = copy.deepcopy(default_value)

    def configure(self, config):
        pass

    def setup(self, config, app_globals):
        pass

    def add_middleware(self, config, app):
        return app


class ListWithPrecedence(object):
    def __init__(self):
        self._dependencies = {}
        self._ordered_elements = []

    def add(self, obj, after=None):
        self._dependencies.setdefault(after, []).append(obj)
        self._resolve_ordering()

    def __repr__(self):
        return '<ListWithPrecedence %s>' % self._ordered_elements

    def __iter__(self):
        return iter(self._ordered_elements)

    def _resolve_ordering(self):
        self._ordered_elements = []

        registered_wrappers = self._dependencies.copy()
        visit_queue = deque([False, None])
        while visit_queue:
            current = visit_queue.popleft()
            if current not in (False, None):
                self._ordered_elements.append(current)

                if not inspect.isclass(current):
                    current = current.__class__

            dependant_wrappers = registered_wrappers.pop(current, [])
            visit_queue.extendleft(reversed(dependant_wrappers))
