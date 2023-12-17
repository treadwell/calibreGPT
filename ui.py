from calibre.gui2.actions import InterfaceAction
from calibre_plugins.calibre_gpt.main import GPTDialog
import subprocess

class InterfacePlugin(InterfaceAction):

    name = 'Calibre GPT'
    action_spec = ('Calibre GPT', None, 'Run the Calibre GPT Plugin', None)
    action_menu_clone_qaction = "Calibre GPT Similar Books"

    def genesis(self):
        text = "Calibre GPT Similar Books"
        from PyQt5.QtWidgets import QAction, QIcon
        icon = get_icons('images/icon.png', 'Calibre GPT Plugin')
        self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_dialog)
        ma = QAction(QIcon.ic(icon), text, self.gui)
        ma.setAutoRepeat(self.auto_repeat)
        ma.setToolTip(text)
        ma.setStatusTip(text)
        ma.setWhatsThis(text)
        self.gui.addAction(ma)
        ma.triggered.connect(self.show_dialog)
        
        # TODO: double check that we need this
        subprocess.run(["pip3", "install", "certifi", "faiss-cpu", "numpy"])

    def show_dialog(self):
        # from PyQt5.QtWidgets import QToolButton
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        d = GPTDialog(self.gui, self.qaction.icon(), do_user_config)
        # print(self.qaction.text(), self.qaction.menu())
        # print([(o, o.parent(), o.sender()) for o in self.qaction.associatedObjects() if type(o) is QToolButton])
        d.show()