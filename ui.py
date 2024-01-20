from calibre.gui2.actions import InterfaceAction
from calibre_plugins.calibre_gpt.main import GPTDialog
import subprocess
import calibre_plugins.calibre_gpt.strings as strings

def show_dialog(gui, qaction, do_user_config, type):
    d = GPTDialog(gui, qaction.icon(), do_user_config, type)
    d.show()

class InterfacePlugin(InterfaceAction):

    name = strings.primary_name
    action_spec = (strings.primary_action_name, None, strings.primary_description, None)
    dont_add_to = frozenset(['context-menu',
        'context-menu-device', 'menubar', 'menubar-device',
        'context-menu-cover-browser', 'context-menu-split', 'searchbar'])

    def genesis(self):
        subprocess.run(["pip3", "install", "certifi", "faiss-cpu", "numpy"])
        self.icon = get_icons('images/icon.png', self.name)
        self.qaction.setIcon(self.icon)
        self.qaction.triggered.connect(self.show)

    def show(self):
        show_dialog(self.gui, self.qaction, self.interface_action_base_plugin.do_user_config, "main")

class InterfacePluginSecondary(InterfaceAction):

    name = strings.secondary_name
    action_spec = (strings.secondary_action_name, None, strings.secondary_description, None)
    dont_add_to = frozenset(['toolbar', 'toolbar-device', 'toolbar-child', 'menubar', 'menubar-device', 'searchbar'])

    def genesis(self):
        self.icon = get_icons('images/icon.png', self.name)
        self.qaction.setIcon(self.icon)
        self.qaction.triggered.connect(self.show)

    def show(self):
        show_dialog(self.gui, self.qaction, self.interface_action_base_plugin.do_user_config, "context")

class InterfacePluginTertiary(InterfaceAction):

    name = strings.tertiary_name
    action_spec = (strings.tertiary_action_name, None, strings.tertiary_description, None)
    dont_add_to = frozenset(['context-menu',
        'context-menu-device', 'menubar', 'menubar-device',
        'context-menu-cover-browser', 'context-menu-split', 'searchbar'])
    
    def genesis(self):
        self.icon = get_icons('images/icon.png', self.name)
        self.qaction.setIcon(self.icon)
        self.qaction.triggered.connect(self.show)

    def show(self):
        show_dialog(self.gui, self.qaction, self.interface_action_base_plugin.do_user_config, "gpt")