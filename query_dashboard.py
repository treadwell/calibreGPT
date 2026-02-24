#!/usr/bin/env python3

import argparse
import html
import json
import os
import subprocess
import statistics
import urllib.parse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

from migration_utils import load_libraries, resolve_book_open_paths, search_similar_chunks


def aggregate_results(results: List[Dict]) -> List[Dict]:
    grouped = {}
    for row in results:
        book_id = int(row["book_id"])
        entry = grouped.get(book_id)
        if entry is None:
            grouped[book_id] = {
                "book_id": book_id,
                "title": row.get("title", ""),
                "author": row.get("author", ""),
                "best_distance": float(row.get("distance", 0.0)),
                "chunk_hits": 1,
                "sample_excerpt": row.get("excerpt", ""),
            }
        else:
            entry["chunk_hits"] += 1
            d = float(row.get("distance", 0.0))
            if d < entry["best_distance"]:
                entry["best_distance"] = d
                entry["sample_excerpt"] = row.get("excerpt", "")
    return sorted(grouped.values(), key=lambda x: (x["best_distance"], -x["chunk_hits"]))


def apply_elbow_cutoff(items: List[Dict], min_results: int = 5) -> List[Dict]:
    if len(items) <= min_results + 1:
        return items
    distances = [x["best_distance"] for x in items]
    diffs = [distances[i + 1] - distances[i] for i in range(len(distances) - 1)]
    if not diffs:
        return items
    mean = statistics.mean(diffs)
    stdev = statistics.pstdev(diffs)
    threshold = mean + (1.5 * stdev)
    cutoff = len(items)
    for i, delta in enumerate(diffs):
        if i + 1 >= min_results and delta > threshold:
            cutoff = i + 1
            break
    return items[:cutoff]


def render_page(
    libraries: List[str],
    selected_library: str,
    embedding_model: str,
    top_k: int,
    query: str,
    use_elbow: bool,
    result_rows: List[Dict],
    error: str,
) -> str:
    library_options = "\n".join(
        [
            f'<option value="{html.escape(lib)}" {"selected" if lib == selected_library else ""}>{html.escape(lib)}</option>'
            for lib in libraries
        ]
    )
    rows = []
    for row in result_rows:
        calibre_filter = f"id:{row['book_id']}"
        rows.append(
            f"""
            <tr>
              <td>{row['book_id']}</td>
              <td>{html.escape(row['title'])}</td>
              <td>{html.escape(row['author'])}</td>
              <td>{row['chunk_hits']}</td>
              <td>{row['best_distance']:.4f}</td>
              <td><code>{html.escape(calibre_filter)}</code></td>
              <td>{row.get('actions_html', '')}</td>
              <td><code>{html.escape(row['sample_excerpt'])}</code></td>
            </tr>
            """
        )
    checked = "checked" if use_elbow else ""
    error_html = f'<p style="color:#b00"><code>{html.escape(error)}</code></p>' if error else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Calibre Query UI</title>
  <style>
    body {{ font-family: Menlo, Monaco, Consolas, monospace; margin: 20px; background:#f6f7f3; color:#1e1f1b; }}
    form {{ background:#fff; border:1px solid #ddd; padding: 12px; margin-bottom: 16px; }}
    label {{ display:block; margin: 8px 0 4px; }}
    input[type=text], select {{ width: 100%; padding: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background:#fff; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #e8ecdf; text-align: left; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
  </style>
</head>
<body>
  <h2>Calibre Semantic Query UI</h2>
  <form method="post" action="/search">
    <label>Library</label>
    <select name="library">{library_options}</select>
    <label>Embedding Model</label>
    <select name="embedding_model">
      <option value="text-embedding-ada-002" {"selected" if embedding_model == "text-embedding-ada-002" else ""}>text-embedding-ada-002</option>
      <option value="text-embedding-3-small" {"selected" if embedding_model == "text-embedding-3-small" else ""}>text-embedding-3-small</option>
      <option value="text-embedding-3-large" {"selected" if embedding_model == "text-embedding-3-large" else ""}>text-embedding-3-large</option>
    </select>
    <label>Top K chunks</label>
    <input type="text" name="top_k" value="{top_k}" />
    <label>Query</label>
    <input type="text" name="query" value="{html.escape(query)}" />
    <label><input type="checkbox" name="use_elbow" value="1" {checked}/> Apply elbow cutoff to likely matches</label>
    <button type="submit">Search</button>
  </form>
  {error_html}
  <table>
    <thead>
      <tr><th>Book ID</th><th>Title</th><th>Author</th><th>Chunk Hits</th><th>Best Distance</th><th>Calibre Filter</th><th>Actions</th><th>Excerpt</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <p id="status" style="margin-top:10px;color:#444"></p>
  <script>
    function showStatus(message) {{
      var el = document.getElementById('status');
      if (el) {{
        el.textContent = message;
      }}
    }}
    function openFile(url) {{
      fetch(url)
        .then(function(res) {{
          if (res.ok) {{
            showStatus('Opened file in default app.');
          }} else {{
            showStatus('Open failed (' + res.status + ').');
          }}
        }})
        .catch(function(err) {{
          showStatus('Open failed: ' + err);
        }});
    }}
    function setDrag(ev, fileUrl, filePath, fileName) {{
      ev.dataTransfer.setData('DownloadURL', 'application/octet-stream:' + fileName + ':' + fileUrl);
      ev.dataTransfer.setData('text/uri-list', fileUrl);
      ev.dataTransfer.setData('text/plain', filePath);
      showStatus('Dragging: ' + fileName);
    }}
  </script>
</body>
</html>"""


def make_handler(engine_path: str, libraries: List[str], active_model: str, batch_size: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/open":
                params = urllib.parse.parse_qs(parsed.query)
                library = params.get("library", [""])[0]
                book_id_raw = params.get("book_id", [""])[0]
                if library not in libraries:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid library")
                    return
                try:
                    book_id = int(book_id_raw)
                except ValueError:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid book_id")
                    return
                mapping = resolve_book_open_paths(library, [book_id])
                if book_id not in mapping:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"No file found for book")
                    return
                target = mapping[book_id]["path"]
                subprocess.Popen(["open", target])
                self.send_response(204)
                self.end_headers()
                return
            if parsed.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            page = render_page(
                libraries=libraries,
                selected_library=libraries[0],
                embedding_model="text-embedding-3-small",
                top_k=50,
                query="",
                use_elbow=False,
                result_rows=[],
                error="",
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = urllib.parse.parse_qs(raw)

            selected_library = data.get("library", [libraries[0]])[0]
            embedding_model = data.get("embedding_model", ["text-embedding-3-small"])[0]
            query = data.get("query", [""])[0].strip()
            use_elbow = data.get("use_elbow", ["0"])[0] == "1"
            try:
                top_k = int(data.get("top_k", ["50"])[0])
                if top_k <= 0 or top_k > 200:
                    raise ValueError
            except ValueError:
                top_k = 50

            rows = []
            error = ""
            if selected_library not in libraries:
                error = "Invalid library selection."
                selected_library = libraries[0]
            elif not query:
                error = "Enter a query."
            else:
                try:
                    raw_results = search_similar_chunks(
                        engine_path=engine_path,
                        library_path=selected_library,
                        embedding_model=embedding_model,
                        active_model=active_model,
                        batch_size=batch_size,
                        query=query,
                        match_count=top_k,
                        skip_sync=True,
                    )
                    rows = aggregate_results(raw_results)
                    book_map = resolve_book_open_paths(selected_library, [r["book_id"] for r in rows])
                    for row in rows:
                        file_info = book_map.get(int(row["book_id"]))
                        if not file_info:
                            row["actions_html"] = ""
                            continue
                        abs_path = file_info["path"]
                        file_name = os.path.basename(abs_path)
                        file_url = "file://" + urllib.parse.quote(abs_path)
                        open_url = (
                            "/open?library="
                            + urllib.parse.quote(selected_library, safe="")
                            + "&book_id="
                            + str(row["book_id"])
                        )
                        row["actions_html"] = (
                            f'<button type="button" onclick="openFile({json.dumps(open_url)})">Open</button> '
                            f'| <a href="{file_url}">File Link</a> '
                            f'| <span draggable="true" ondragstart="setDrag(event, {json.dumps(file_url)}, {json.dumps(abs_path)}, {json.dumps(file_name)})" '
                            f'style="cursor:grab;text-decoration:underline;font-weight:600">Drag File</span>'
                        )
                    if use_elbow:
                        rows = apply_elbow_cutoff(rows)
                except Exception as exc:
                    error = str(exc)

            page = render_page(
                libraries=libraries,
                selected_library=selected_library,
                embedding_model=embedding_model,
                top_k=top_k,
                query=query,
                use_elbow=use_elbow,
                result_rows=rows,
                error=error,
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def log_message(self, fmt, *args):
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(prog="query_dashboard")
    parser.add_argument("--engine", default="./engine.py")
    parser.add_argument("--libraries-file")
    parser.add_argument("--library-path", action="append", default=[])
    parser.add_argument("--active-model", default="text-embedding-ada-002")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()

    libraries = load_libraries(args.libraries_file, args.library_path)
    engine_path = os.path.abspath(args.engine)
    if not os.path.exists(engine_path):
        raise ValueError(f"Engine not found: {engine_path}")

    handler = make_handler(engine_path, libraries, args.active_model, args.batch_size)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Query UI running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
