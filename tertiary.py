from calibre.customize import InterfaceActionBase
import calibre_plugins.calibre_gpt.strings as strings

class CalibreGPTTertiary(InterfaceActionBase):
    name                = strings.tertiary_name
    description         = strings.tertiary_description
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Ken Brooks'
    version             = strings.version
    minimum_calibre_version = (0, 7, 53)
    actual_plugin       = 'calibre_plugins.calibre_gpt.ui:InterfacePluginTertiary'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.calibre_gpt.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()