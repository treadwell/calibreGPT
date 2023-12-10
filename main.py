from qt.core import QDialog, QVBoxLayout, QPushButton, QLabel
from PyQt5.Qt import QLineEdit
from calibre.utils.config_base import prefs as base_prefs
from calibre_plugins.calibre_gpt.config import prefs
from calibre.db.legacy import LibraryDatabase
from calibre.ptempfile import TemporaryFile
import sys

# from calibre_plugins.calibre_gpt.engine import run_query
import subprocess
import os
import json

class GPTDialog(QDialog):

    def __init__(self, gui, icon, do_user_config):
        QDialog.__init__(self, gui)
        self.icon = icon
        self.gui = gui
        self.do_user_config = do_user_config
        self.lib_path = base_prefs['library_path']
        self.legacy_db = LibraryDatabase(base_prefs["library_path"])

        # The current database shown in the GUI
        # db is an instance of the class LibraryDatabase from db/legacy.py
        # This class has many, many methods that allow you to do a lot of
        # things. For most purposes you should use db.new_api, which has
        # a much nicer interface from db/cache.py
        self.db = gui.current_db

        self.l = QVBoxLayout()
        self.setLayout(self.l)

        self.setWindowTitle('Calibre GPT')
        self.setWindowIcon(icon)

        self.token = prefs['open_ai_token']
        
        if not self.token:
            self.l.addWidget(QLabel('Add token in configuration window!'))
        else:
            rows = self.gui.library_view.selectionModel().selectedRows()
            ids = list(map(self.gui.library_view.model().id, rows))
            if len(ids) > 0:
                self.search_book = QPushButton('Search for books similar to the ' +
                                               str(len(ids)) +
                                               ' you have selected.', self)
                self.l.addWidget(self.search_book)
                self.search_book.clicked.connect(lambda: self.query_book(ids))
            self.l.addWidget(QLabel('otherwise enter a query and press search.'))
            self.prompt = QLineEdit()
            self.l.addWidget(self.prompt)
            self.search_text = QPushButton('Search', self)
            self.l.addWidget(self.search_text)
            self.search_text.clicked.connect(self.query_text)

        self.conf_button = QPushButton('Configure this plugin', self)
        self.conf_button.clicked.connect(self.config)
        self.l.addWidget(self.conf_button)

        self.resize(self.sizeHint())
    
    def query_text(self):
        data = json.loads(self.exec_query(["--prompt", self.prompt.text()]).decode("utf-8"))
        matched_ids = [d["book_id"] for d in data]
        self.db.set_marked_ids(matched_ids)
        self.gui.search.setEditText('marked:true')
        self.gui.search.do_search()
        for d in data:
            metadata = self.db.get_metadata(d["book_id"], index_is_id=True)
            metadata.set('#calibregpt_distance', d["distance"])
            self.db.set_metadata(d["book_id"], metadata, set_title=False, set_authors=False, commit=True)
        self.close()

    def query_book(self, ids):
        data = json.loads(self.exec_query(["--ids", ",".join([str(id) for id in ids])]).decode("utf-8"))
        matched_ids = [d["book_id"] for d in data]
        self.db.set_marked_ids(matched_ids)
        self.gui.search.setEditText('marked:true')
        self.gui.search.do_search()
        for d in data:
            metadata = self.db.get_metadata(d["book_id"], index_is_id=True)
            metadata.set('#calibregpt_distance', d["distance"])
            self.db.set_metadata(d["book_id"], metadata, set_title=False, set_authors=False, commit=True)
        self.close()

    def exec_query(self, flags):
        engine = subprocess.Popen(["python3", "-", 
            "--openai-token", self.token,
            "--fulltext-db", os.path.join(self.lib_path, 'full-text-search.db'), 
            "--metadata-db", os.path.join(self.lib_path, 'metadata.db'), 
            "--calibregpt-db", os.path.join(self.lib_path, 'calibregpt.db'), 
            "--faiss-index", os.path.join(self.lib_path, 'faiss.idx'), 
            "--match-count", "50"] + flags, 
            stdout = subprocess.PIPE, 
            stderr = subprocess.PIPE, 
            stdin = subprocess.PIPE)
        res = engine.communicate(input = get_resources("engine.py"))
        print("stdout: ", res[0], file = sys.stderr)
        print("stderr: ", res[1], file = sys.stderr)
        return res[0]

    def config(self):
        self.do_user_config(parent=self)
        self.done(0)
        self.__init__(self.gui, self.icon, self.do_user_config)
        self.show()