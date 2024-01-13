from PyQt5.Qt import QWidget, QLabel, QLineEdit, QVBoxLayout, QCheckBox
from calibre.utils.config import JSONConfig

# This is where all preferences for this plugin will be stored
# Remember that this name (i.e. plugins/interface_demo) is also
# in a global namespace, so make it as unique as possible.
# You should always prefix your config file name with plugins/,
# so as to ensure you don't accidentally clobber a calibre config file
prefs = JSONConfig('plugins/calibre_gpt')

# Set defaults
prefs.defaults['open_ai_token'] = ''
prefs.defaults['debug'] = False

class ConfigWidget(QWidget): 

    def __init__(self):
        QWidget.__init__(self)
        self.l = QVBoxLayout()
        self.setLayout(self.l)

        self.label = QLabel('OpenAI Token:')
        self.l.addWidget(self.label)

        self.token = QLineEdit(self)
        self.token.setText(prefs['open_ai_token'])
        self.l.addWidget(self.token)

        self.debug = QCheckBox('Debug mode enabled', self)
        self.debug.setChecked(prefs['debug'])
        self.l.addWidget(self.debug)

    def save_settings(self):
        prefs['open_ai_token'] = self.token.text()
        prefs['debug'] = self.debug.isChecked()