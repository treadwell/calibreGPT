from qt.core import QDialog, QVBoxLayout, QPushButton, QLabel, QMessageBox
from PyQt5.Qt import QLineEdit
from calibre.utils.config_base import prefs as base_prefs
from calibre_plugins.calibre_gpt.config import prefs as calibregpt_prefs
from calibre.db.legacy import LibraryDatabase
from calibre.ptempfile import TemporaryFile
import sys
import subprocess
import os
import json

class GPTDialog(QDialog):

    def __init__(self, gui, icon, do_user_config, type):
        QDialog.__init__(self, gui)
        self.icon = icon
        self.gui = gui
        self.do_user_config = do_user_config
        self.legacy_db = LibraryDatabase(base_prefs["library_path"])
        self.db_dir = os.path.dirname(self.legacy_db.dbpath)

        self.db = gui.current_db

        self.l = QVBoxLayout()
        self.setLayout(self.l)

        self.setWindowTitle('Calibre GPT')
        self.setWindowIcon(icon)

        self.token = calibregpt_prefs['open_ai_token']
        
        if not self.token:
            self.l.addWidget(QLabel('Add token in configuration window!'))
        elif type == 'main':
            self.l.addWidget(QLabel('Enter a query and press search.'))
            self.prompt = QLineEdit()
            self.l.addWidget(self.prompt)
            self.search_text = QPushButton('Search', self)
            self.l.addWidget(self.search_text)
            self.search_text.clicked.connect(self.query_text)
        elif type == 'context':
            rows = self.gui.library_view.selectionModel().selectedRows()
            ids = list(map(self.gui.library_view.model().id, rows))
            self.l.addWidget(QLabel(f'Search for books similar to the {str(len(ids))} you have selected.'))
            self.search_book = QPushButton('Search', self)
            self.l.addWidget(self.search_book)
            self.search_book.clicked.connect(lambda: self.query_book(ids))
        else:
            raise ValueError("Invalid type: main or context expected, received " + type)

        self.conf_button = QPushButton('Configure this plugin', self)
        self.conf_button.clicked.connect(self.config)
        self.l.addWidget(self.conf_button)

        self.resize(self.sizeHint())
    
    def query_text(self):
        data = self.exec_query(["--prompt", self.prompt.text()])
        if data == None:
            return
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
        data = self.exec_query(["--ids", ",".join([str(id) for id in ids])])
        if data == None:
            return
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
            "--fulltext-db", os.path.join(self.db_dir, 'full-text-search.db'), 
            "--metadata-db", os.path.join(self.db_dir, 'metadata.db'), 
            "--calibregpt-db", os.path.join(self.db_dir, 'calibregpt.db'), 
            "--faiss-index", os.path.join(self.db_dir, 'faiss.idx'), 
            "--match-count", "50"] + flags, 
            stdout = subprocess.PIPE, 
            stderr = subprocess.PIPE, 
            stdin = subprocess.PIPE)
        res = engine.communicate(input = get_resources("engine.py"))
        data = json.loads(res[0].decode("utf-8"))
        if "error" in data:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Error")
            msg.setInformativeText(data["error"])
            msg.setWindowTitle("Error")
            msg.exec_()
            return None
        return data["results"]

    def config(self):
        self.do_user_config(parent=self)
        self.done(0)
        self.__init__(self.gui, self.icon, self.do_user_config)
        self.show()