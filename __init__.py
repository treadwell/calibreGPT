import calibre_plugins.calibre_gpt.strings as strings
from calibre.customize import InterfaceActionBase

from apsw import ConstraintError
from calibre.utils.config_base import prefs as base_prefs
from calibre.db.legacy import LibraryDatabase

db = LibraryDatabase(base_prefs["library_path"])
try:
    db.create_custom_column("calibregpt_distance", "CalibreGPT Distance", "float", 0)
except ConstraintError:
    pass

class CalibreGPT(InterfaceActionBase):
    name                = strings.primary_name
    description         = strings.primary_description
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Ken Brooks'
    version             = strings.version
    minimum_calibre_version = (0, 7, 53)
    actual_plugin       = 'calibre_plugins.calibre_gpt.ui:InterfacePlugin'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.calibre_gpt.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()

    def initialize(self):
        print("initialize is running")
        from calibre.customize.ui import _initialized_plugins
        from calibre_plugins.calibre_gpt.secondary import CalibreGPTSecondary
        for plugin in _initialized_plugins:
            if isinstance(plugin, CalibreGPTSecondary):
                break
        plugin = CalibreGPTSecondary(self.plugin_path)
        _initialized_plugins.append(plugin)
        plugin.initialize()