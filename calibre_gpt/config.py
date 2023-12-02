from PyQt5.Qt import QWidget, QLabel, QLineEdit, QHBoxLayout
from calibre.utils.config import JSONConfig

# This is where all preferences for this plugin will be stored
# Remember that this name (i.e. plugins/interface_demo) is also
# in a global namespace, so make it as unique as possible.
# You should always prefix your config file name with plugins/,
# so as to ensure you dont accidentally clobber a calibre config file
prefs = JSONConfig('plugins/calibre_gpt')

# Set defaults
prefs.defaults['open_ai_token'] = ''


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        self.l = QHBoxLayout()
        self.setLayout(self.l)

        self.label = QLabel('OpenAI Token:')
        self.l.addWidget(self.label)

        self.token = QLineEdit(self)
        self.token.setText(prefs['open_ai_token'])
        self.l.addWidget(self.token)

    def save_settings(self):
        prefs['open_ai_token'] = self.token.text()