from calibre.customize import InterfaceActionBase
import calibre_plugins.calibre_gpt.strings as strings

class CalibreGPTSecondary(InterfaceActionBase):
    name                = strings.secondary_name
    description         = strings.secondary_description
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Ken Brooks'
    version             = strings.version
    minimum_calibre_version = (0, 7, 53)
    actual_plugin       = 'calibre_plugins.calibre_gpt.ui:InterfacePluginSecondary'

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