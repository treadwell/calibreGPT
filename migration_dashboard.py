#!/usr/bin/env python3

import argparse
import html
import json
import os
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

from migration_utils import load_libraries, migrate_once, migration_status


@dataclass
class LibraryState:
    path: str
    running: bool = False
    busy: bool = False
    last_status: Dict = field(default_factory=dict)
    last_migration: Dict = field(default_factory=dict)
    last_error: str = ""
    worker: threading.Thread = None


class MigrationDashboard:
    def __init__(self, engine_path: str, libraries: List[str], embedding_model: str, active_model: str, batch_size: int, sleep_seconds: int):
        self.engine_path = engine_path
        self.embedding_model = embedding_model
        self.active_model = active_model
        self.batch_size = batch_size
        self.sleep_seconds = sleep_seconds
        self.lock = threading.Lock()
        self.states: Dict[str, LibraryState] = {lib: LibraryState(path=lib) for lib in libraries}

    def refresh_status(self, library_path: str) -> None:
        state = self.states[library_path]
        try:
            status = migration_status(
                engine_path=self.engine_path,
                library_path=library_path,
                embedding_model=self.embedding_model,
                active_model=self.active_model,
                batch_size=self.batch_size,
            )
            with self.lock:
                state.last_status = status
                state.last_error = ""
        except Exception as exc:
            with self.lock:
                state.last_error = str(exc)

    def migrate_once(self, library_path: str) -> None:
        state = self.states[library_path]
        try:
            result = migrate_once(
                engine_path=self.engine_path,
                library_path=library_path,
                embedding_model=self.embedding_model,
                active_model=self.active_model,
                batch_size=self.batch_size,
            )
            with self.lock:
                state.last_migration = result
                state.last_error = ""
            self.refresh_status(library_path)
        except Exception as exc:
            with self.lock:
                state.last_error = str(exc)

    def _worker_loop(self, library_path: str) -> None:
        while True:
            with self.lock:
                state = self.states[library_path]
                if not state.running:
                    return
                state.busy = True
            self.refresh_status(library_path)
            with self.lock:
                remaining = state.last_status.get("remaining", 0)
            if remaining == 0:
                with self.lock:
                    state.running = False
                    state.busy = False
                return
            self.migrate_once(library_path)
            with self.lock:
                state.busy = False
            time.sleep(self.sleep_seconds)

    def start(self, library_path: str) -> None:
        with self.lock:
            state = self.states[library_path]
            if state.running:
                return
            state.running = True
            state.worker = threading.Thread(target=self._worker_loop, args=(library_path,), daemon=True)
            state.worker.start()

    def pause(self, library_path: str) -> None:
        with self.lock:
            self.states[library_path].running = False

    def run_once_async(self, library_path: str) -> None:
        with self.lock:
            state = self.states[library_path]
            if state.running or state.busy:
                return
            state.busy = True

        def _run_once():
            try:
                self.refresh_status(library_path)
                with self.lock:
                    remaining = self.states[library_path].last_status.get("remaining", 0)
                if remaining > 0:
                    self.migrate_once(library_path)
            finally:
                with self.lock:
                    self.states[library_path].busy = False

        t = threading.Thread(target=_run_once, daemon=True)
        with self.lock:
            state.worker = t
        t.start()

    def snapshot(self) -> Dict[str, Dict]:
        with self.lock:
            return {
                lib: {
                    "running": st.running,
                    "busy": st.busy,
                    "last_status": dict(st.last_status),
                    "last_migration": dict(st.last_migration),
                    "last_error": st.last_error,
                }
                for lib, st in self.states.items()
            }


def make_handler(app: MigrationDashboard):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            snapshot = app.snapshot()
            body = render_dashboard(snapshot, app.embedding_model, app.active_model, app.batch_size)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def do_POST(self):
            if self.path != "/action":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = urllib.parse.parse_qs(raw)
            action = data.get("action", [""])[0]
            library = data.get("library", [""])[0]
            if library not in app.states:
                self.send_response(400)
                self.end_headers()
                return
            if action == "start":
                app.start(library)
            elif action == "pause":
                app.pause(library)
            elif action == "run_once":
                app.run_once_async(library)
            elif action == "refresh":
                app.refresh_status(library)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    return Handler


def render_dashboard(snapshot: Dict[str, Dict], embedding_model: str, active_model: str, batch_size: int) -> str:
    rows = []
    for library, state in snapshot.items():
        status = state.get("last_status", {})
        migration = state.get("last_migration", {})
        error = state.get("last_error", "")
        rows.append(
            f"""
            <tr>
              <td><code>{html.escape(library)}</code></td>
              <td>{'RUNNING' if state.get('running') else ('BUSY' if state.get('busy') else 'PAUSED')}</td>
              <td>{status.get('up_to_date', '-')}/{status.get('total_chunks', '-')}</td>
              <td>{status.get('remaining', '-')}</td>
              <td>{status.get('progress_percent', '-')}%</td>
              <td><code>{html.escape(json.dumps(migration)) if migration else ''}</code></td>
              <td style="color:#b00"><code>{html.escape(error)}</code></td>
              <td>
                <form method="post" action="/action">
                  <input type="hidden" name="library" value="{html.escape(library)}" />
                  <button name="action" value="start">Start</button>
                  <button name="action" value="pause">Pause</button>
                  <button name="action" value="run_once">Run Once</button>
                  <button name="action" value="refresh">Refresh</button>
                </form>
              </td>
            </tr>
            """
        )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Calibre Migration Dashboard</title>
  <style>
    body {{ font-family: Menlo, Monaco, Consolas, monospace; margin: 20px; background:#f7f7f5; color:#1f1f1f; }}
    table {{ width: 100%; border-collapse: collapse; background:#fff; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f0ebe0; text-align: left; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
    button {{ margin-right: 6px; }}
  </style>
</head>
<body>
  <h2>Calibre Embedding Migration Dashboard</h2>
  <p>embedding_model=<code>{html.escape(embedding_model)}</code> active_model=<code>{html.escape(active_model)}</code> batch_size=<code>{batch_size}</code></p>
  <p>Set <code>OPENAI_TOKEN</code> in shell before starting this dashboard for migrate actions.</p>
  <table>
    <thead>
      <tr>
        <th>Library</th><th>Mode</th><th>Up To Date</th><th>Remaining</th><th>Progress</th><th>Last Batch</th><th>Error</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(prog="migration_dashboard")
    parser.add_argument("--engine", default="./engine.py")
    parser.add_argument("--libraries-file")
    parser.add_argument("--library-path", action="append", default=[])
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--active-model", default="text-embedding-ada-002")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--sleep-seconds", type=int, default=2)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    libraries = load_libraries(args.libraries_file, args.library_path)
    engine_path = os.path.abspath(args.engine)
    if not os.path.exists(engine_path):
        raise ValueError(f"Engine not found: {engine_path}")

    app = MigrationDashboard(
        engine_path=engine_path,
        libraries=libraries,
        embedding_model=args.embedding_model,
        active_model=args.active_model,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep_seconds,
    )
    handler = make_handler(app)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Dashboard running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
