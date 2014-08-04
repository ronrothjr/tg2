import warnings
from tg.configuration import milestones
from tg.request_local import config as reqlocal_config
from tg.wsgiapp import TGApp
from tg.util import Bunch, DottedFileNameFinder
from .utils import ListWithPrecedence, TGConfigError, ConfigurationFeature, get_partial_dict
from .hooks import hooks
import logging
import os

log = logging.getLogger(__name__)


class Configurator(object):
    def __init__(self):
        self._features = ListWithPrecedence()
        self.config = Bunch({
            'debug': False,
            'tg.app_globals': Bunch(),
            'package': None,
            'package_name': None,
            'paths': Bunch({'root': None,
                            'controllers': None,
                            'templates': ['.'],
                            'static_files': '.'})
        })

        self.add_feature(I18NSupport)
        self.add_feature(TemplateEnginesSupport)
        self.add_feature(RegistrySupport, after=TemplateEnginesSupport)

    def add_feature(self, feature, after=None):
        self._features.add(feature(self.config), after)

    def bind_package(self, package):
        self.config.package = package
        self.config.package_name = package.__name__

        root = os.path.dirname(os.path.abspath(self.config.__file__))
        self.config.paths = Bunch(root=root,
                                  controllers=os.path.join(root, 'controllers'),
                                  static_files=os.path.join(root, 'public'),
                                  templates=[os.path.join(root, 'templates')])

        try:
            g = package.lib.app_globals.Globals()
        except AttributeError:
            log.warn('Application has a package but no lib.app_globals.Globals class is available.')
        else:
            self.config['tg.app_globals'] = g

    def bind_root_controller(self, controller_instance):
        self.config['tg.root_controller'] = controller_instance

    def _configure(self, app_config=None, env_config=None):
        self.config.update(app_config or {})
        self.config.update(env_config or {})

        for config_step in self._features:
            config_step.configure(self.config)

        reqlocal_config.push_process_config(self.config)
        milestones.config_ready.reach()

    def _setup(self):
        app_globals = self.config['tg.app_globals']
        app_globals.dotted_filename_finder = DottedFileNameFinder()

        for config_step in self._features:
            config_step.setup(self.config, app_globals)

    def make_wsgi_app(self, env_config=None, **app_config):
        self._configure(app_config, env_config)
        self._setup()

        app = TGApp(config=self.config)
        app = hooks.notify_with_value('before_config', app, context_config=self.config)

        for config_step in self._features:
            app = config_step.add_middleware(self.config, app)

        app = hooks.notify_with_value('after_config', app, context_config=self.config)
        return app


from tg.support.registry import RegistryManager
from tg.support.converters import asbool


class RegistrySupport(ConfigurationFeature):
    CONFIG_NAMESPACE = 'registry.'
    CONFIG_OPTIONS = {
        'streaming': asbool
    }
    CONFIG_DEFAULTS = {
        'streaming': True
    }

    def configure(self, config):
        if 'registry_streaming' in config:
            warnings.warn("registry_streaming got deprecated in favor of registry.streaming",
                          DeprecationWarning, stacklevel=2)
            config['registry.streaming'] = config['registry_streaming']

    def add_middleware(self, config, app):
        return RegistryManager(app, streaming=config['registry.streaming'],
                               preserve_exceptions=config['debug'])


from tg.support.converters import asbool


class I18NSupport(ConfigurationFeature):
    CONFIG_NAMESPACE = 'i18n.'
    CONFIG_OPTIONS = {
        'enabled': asbool
    }
    CONFIG_DEFAULTS = {
        'enabled': False,
        'lang': None
    }

from tg.support.converters import aslist, asbool
from tg.renderers.genshi import GenshiRenderer
from tg.renderers.json import JSONRenderer
from tg.renderers.jinja import JinjaRenderer
from tg.renderers.mako import MakoRenderer
from tg.renderers.kajiki import KajikiRenderer


class TemplateEngines(object):
    def __init__(self):
        self.engines = {}
        self.engines_options = {}
        self.engines_without_vars = set()

    def add(self, factory):
        """Registers a rendering engine ``factory``.

        Rendering engine factories are :class:`tg.renderers.base.RendererFactory`
        subclasses in charge of creating a rendering engine.

        """
        for engine, options in factory.engines.items():
            self.engines[engine] = factory
            self.engines_options[engine] = options
            if factory.with_tg_vars is False:
                self.engines_without_vars.add(engine)


class TemplateEnginesSupport(ConfigurationFeature):
    CONFIG_NAMESPACE = 'templating.'
    CONFIG_OPTIONS = {
        'auto_reload': asbool,
        'renderers': aslist,
    }
    CONFIG_DEFAULTS = {
        'auto_reload': True,
        'renderers': [],
        'default': 'genshi',
        'engines': TemplateEngines(),
        'render_functions': {}
    }

    def configure(self, config):
        tmpl_conf = get_partial_dict(self.CONFIG_NAMESPACE, config, Bunch)

        tmpl_conf.engines.add(JSONRenderer)
        tmpl_conf.engines.add(GenshiRenderer)
        tmpl_conf.engines.add(MakoRenderer)
        tmpl_conf.engines.add(JinjaRenderer)
        tmpl_conf.engines.add(KajikiRenderer)

        if not 'json' in tmpl_conf.renderers:
            tmpl_conf.renderers.append('json')

        if tmpl_conf.default not in tmpl_conf.renderers:
            first_renderer = tmpl_conf.renderers[0]
            log.warning('Default renderer not in renders, '
                        'automatically switching to %s', first_renderer)
            tmpl_conf.default = first_renderer

    def setup(self, config, app_globals):
        tmpl_conf = get_partial_dict(self.CONFIG_NAMESPACE, config, Bunch)

        for renderer in tmpl_conf.renderers[:]:
            if renderer in tmpl_conf.engines.engines:
                rendering_engine = tmpl_conf.engines.engines[renderer]
                engines = rendering_engine.create(config, app_globals)
                if engines is None:
                    log.error('Failed to initialize %s template engine, removing it...' % renderer)
                    tmpl_conf.renderers.remove(renderer)
                else:
                    tmpl_conf.render_functions.update(engines)
            else:
                raise TGConfigError('This configuration object does '
                                    'not support the %s renderer' % renderer)

        milestones.renderers_ready.reach()




