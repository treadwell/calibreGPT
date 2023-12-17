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
    name                = 'Calibre GPT'
    description         = 'Access GPT with Calibre'
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Ken Brooks'
    version             = (1, 0, 7)
    minimum_calibre_version = (0, 7, 53)
    actual_plugin       = 'calibre_plugins.calibre_gpt.ui:InterfacePlugin'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.calibre_gpt.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
        ac = self.actual_plugin_
        if ac is not None:
            ac.apply_settings()