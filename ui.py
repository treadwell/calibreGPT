from calibre.gui2.actions import InterfaceAction
from calibre_plugins.calibre_gpt.main import GPTDialog
from PyQt5.QtWidgets import QAction, QIcon
import subprocess

def show_dialog(gui, qaction, do_user_config, type):
    # base_plugin_object = self.interface_action_base_plugin
    # do_user_config = base_plugin_object.do_user_config
    # d = GPTDialog(self.gui, self.qaction.icon(), do_user_config, type)
    d = GPTDialog(gui, qaction.icon(), do_user_config, type)
    d.show()

class InterfacePlugin(InterfaceAction):

    name = 'Calibre GPT Query Books'
    action_spec = ('Calibre GPT', None, 'Run the Calibre GPT Plugin', None)

    def initialize(self):
        self.gui.add_iaction(InterfacePluginSecondary(self.gui, None))
        # Need properties to make it popup...try another function
        # something other than genesis().

    def genesis(self):
        subprocess.run(["pip3", "install", "certifi", "faiss-cpu", "numpy"])
        self.icon = get_icons('images/icon.png', self.name)
        self.qaction.setIcon(self.icon)
        self.qaction.triggered.connect(self.show)

    def show(self):
        show_dialog(self.gui, self.qaction, self.interface_action_base_plugin.do_user_config, "main")

class InterfacePluginSecondary(InterfaceAction):

    name = 'Calibre GPT Similar Books'
    action_spec = ('Calibre GPT', None, 'Run the Calibre GPT Plugin', None)

    def genesis(self):
        self.icon = get_icons('images/icon.png', self.name)
        self.qaction.setIcon(self.icon)
        self.qaction.triggered.connect(self.show)

    def show(self):
        show_dialog(self.gui, self.qaction, self.interface_action_base_plugin.do_user_config, "context")