#!/usr/bin/env python3

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import statistics
import urllib.parse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Tuple

from migration_utils import load_books_with_tags, load_libraries, load_tags_for_books, resolve_book_open_paths, search_similar_chunks


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


TOKEN_RE = re.compile(r'\s*(\(|\)|"[^"]*"|\'[^\']*\'|AND|OR|NOT|[^()\s]+)\s*', re.IGNORECASE)


def tokenize_tag_expr(expr: str) -> List[str]:
    tokens: List[str] = []
    pos = 0
    while pos < len(expr):
        match = TOKEN_RE.match(expr, pos)
        if not match:
            raise ValueError(f"Invalid token near: {expr[pos:pos+20]}")
        token = match.group(1)
        pos = match.end()
        if token and token.strip():
            tokens.append(token)
    return tokens


def normalize_term(token: str) -> str:
    value = token.strip()
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        value = value[1:-1]
    return value.strip().lower()


def parse_tag_expression(expr: str):
    tokens = tokenize_tag_expr(expr)
    if not tokens:
        raise ValueError("Tag expression is empty.")
    index = 0

    def parse_expr():
        nonlocal index
        node = parse_term()
        while index < len(tokens) and tokens[index].upper() == "OR":
            index += 1
            node = ("OR", node, parse_term())
        return node

    def parse_term():
        nonlocal index
        node = parse_factor()
        while index < len(tokens) and tokens[index].upper() == "AND":
            index += 1
            node = ("AND", node, parse_factor())
        return node

    def parse_factor():
        nonlocal index
        if index >= len(tokens):
            raise ValueError("Unexpected end of tag expression.")
        tok = tokens[index]
        tok_upper = tok.upper()
        if tok_upper == "NOT":
            index += 1
            return ("NOT", parse_factor())
        if tok == "(":
            index += 1
            node = parse_expr()
            if index >= len(tokens) or tokens[index] != ")":
                raise ValueError("Missing closing ')' in tag expression.")
            index += 1
            return node
        if tok in (")", "AND", "OR"):
            raise ValueError(f"Unexpected token: {tok}")
        index += 1
        return ("TERM", normalize_term(tok))

    ast = parse_expr()
    if index != len(tokens):
        raise ValueError(f"Unexpected token: {tokens[index]}")
    return ast


def eval_tag_ast(ast, tags_lower: List[str]) -> bool:
    kind = ast[0]
    if kind == "TERM":
        needle = ast[1]
        return any(needle in tag for tag in tags_lower)
    if kind == "NOT":
        return not eval_tag_ast(ast[1], tags_lower)
    if kind == "AND":
        return eval_tag_ast(ast[1], tags_lower) and eval_tag_ast(ast[2], tags_lower)
    if kind == "OR":
        return eval_tag_ast(ast[1], tags_lower) or eval_tag_ast(ast[2], tags_lower)
    raise ValueError(f"Unknown AST node: {kind}")


def apply_tag_boolean_filter(rows: List[Dict], tag_map: Dict[int, List[str]], expression: str) -> Tuple[List[Dict], str]:
    expr = expression.strip()
    if not expr:
        for row in rows:
            tags = tag_map.get(int(row["book_id"]), [])
            row["tags_display"] = ", ".join(tags)
        return rows, ""
    ast = parse_tag_expression(expr)
    filtered = []
    for row in rows:
        tags = tag_map.get(int(row["book_id"]), [])
        tags_lower = [x.lower() for x in tags]
        if eval_tag_ast(ast, tags_lower):
            row["tags_display"] = ", ".join(tags)
            filtered.append(row)
    return filtered, ""


def render_page(
    libraries: List[str],
    selected_library: str,
    embedding_model: str,
    top_k: int,
    query: str,
    semantic_tag_expr: str,
    tag_expr: str,
    use_elbow: bool,
    semantic_rows: List[Dict],
    tag_rows: List[Dict],
    semantic_error: str,
    tag_error: str,
) -> str:
    library_options = "\n".join(
        [
            f'<option value="{html.escape(lib)}" {"selected" if lib == selected_library else ""}>{html.escape(lib)}</option>'
            for lib in libraries
        ]
    )
    semantic_result_rows = []
    for row in semantic_rows:
        calibre_filter = f"id:{row['book_id']}"
        semantic_result_rows.append(
            f"""
            <tr>
              <td>{row['book_id']}</td>
              <td>{html.escape(row['title'])}</td>
              <td>{html.escape(row['author'])}</td>
              <td>{row['chunk_hits']}</td>
              <td>{row['best_distance']:.4f}</td>
              <td><code>{html.escape(row.get('tags_display', ''))}</code></td>
              <td><code>{html.escape(calibre_filter)}</code></td>
              <td>{row.get('actions_html', '')}</td>
              <td><code>{html.escape(row['sample_excerpt'])}</code></td>
            </tr>
            """
        )
    tag_result_rows = []
    for row in tag_rows:
        calibre_filter = f"id:{row['book_id']}"
        tag_result_rows.append(
            f"""
            <tr>
              <td>{row['book_id']}</td>
              <td>{html.escape(row['title'])}</td>
              <td>{html.escape(row['author'])}</td>
              <td>{row['tag_hits']}</td>
              <td><code>{html.escape(row.get('tags_display', ''))}</code></td>
              <td><code>{html.escape(calibre_filter)}</code></td>
              <td>{row.get('actions_html', '')}</td>
            </tr>
            """
        )
    checked = "checked" if use_elbow else ""
    semantic_error_html = f'<p style="color:#b00"><code>{html.escape(semantic_error)}</code></p>' if semantic_error else ""
    tag_error_html = f'<p style="color:#b00"><code>{html.escape(tag_error)}</code></p>' if tag_error else ""
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
    .bulk-controls {{ background:#fff; border:1px solid #ddd; padding:10px; margin: 10px 0 12px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
    .bulk-controls button {{ padding: 6px 10px; }}
    .bulk-drag {{ display:inline-block; padding:6px 10px; border:1px solid #888; border-radius:4px; background:#f1f1ee; cursor:grab; user-select:none; }}
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
    <label>Tag Boolean Filter (optional)</label>
    <input type="text" name="semantic_tag_expr" value="{html.escape(semantic_tag_expr)}" placeholder='example: meetings AND NOT "workshop"' />
    <label><input type="checkbox" name="use_elbow" value="1" {checked}/> Apply elbow cutoff to likely matches</label>
    <button type="submit">Search</button>
  </form>
  {semantic_error_html}
  <div class="bulk-controls">
    <button type="button" onclick="setSelectionForTable('semantic-results', true)">Select All Semantic</button>
    <button type="button" onclick="setSelectionForTable('semantic-results', false)">Clear Semantic</button>
    <span id="bulkDragSemantic" class="bulk-drag" draggable="true" ondragstart="setBulkDrag(event, 'semantic-results')">Drag Selected Semantic Files</span>
  </div>
  <table>
    <thead>
      <tr><th>Book ID</th><th>Title</th><th>Author</th><th>Chunk Hits</th><th>Best Distance</th><th>Tags</th><th>Calibre Filter</th><th>Actions</th><th>Excerpt</th></tr>
    </thead>
    <tbody>
      {''.join(semantic_result_rows)}
    </tbody>
  </table>
  <h2 style="margin-top:28px">Tag Search</h2>
  <form method="post" action="/search-tag">
    <label>Library</label>
    <select name="library">{library_options}</select>
    <label>Boolean Tag Query</label>
    <input type="text" name="tag_expr" value="{html.escape(tag_expr)}" placeholder='example: meetings AND (project OR planning) AND NOT archived' />
    <p style="margin:6px 0;color:#555">Use <code>AND</code>, <code>OR</code>, <code>NOT</code>, parentheses, and quotes for multi-word tags.</p>
    <button type="submit">Search Tags</button>
  </form>
  {tag_error_html}
  <div class="bulk-controls">
    <button type="button" onclick="setSelectionForTable('tag-results', true)">Select All Tag Results</button>
    <button type="button" onclick="setSelectionForTable('tag-results', false)">Clear Tag Results</button>
    <span id="bulkDragTag" class="bulk-drag" draggable="true" ondragstart="setBulkDrag(event, 'tag-results')">Drag Selected Tag Files</span>
  </div>
  <table>
    <thead>
      <tr><th>Book ID</th><th>Title</th><th>Author</th><th>Tag Count</th><th>Tags</th><th>Calibre Filter</th><th>Actions</th></tr>
    </thead>
    <tbody>
      {''.join(tag_result_rows)}
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
            return res.text().then(function(t) {{
              showStatus('Open failed (' + res.status + '): ' + t);
            }});
          }}
        }})
        .catch(function(err) {{
          showStatus('Open failed: ' + err);
        }});
    }}
    function openFileLink(fileUrl) {{
      try {{
        var a = document.createElement('a');
        a.href = fileUrl;
        a.target = '_self';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        showStatus('Opening file link.');
      }} catch (err) {{
        try {{
          window.location.href = fileUrl;
          showStatus('Opening file link.');
        }} catch (innerErr) {{
          showStatus('Open failed: ' + innerErr);
        }}
      }}
    }}
    function revealFile(url) {{
      fetch(url)
        .then(function(res) {{
          if (res.ok) {{
            showStatus('Revealed file in Finder.');
          }} else {{
            return res.text().then(function(t) {{
              showStatus('Reveal failed (' + res.status + '): ' + t);
            }});
          }}
        }})
        .catch(function(err) {{
          showStatus('Reveal failed: ' + err);
        }});
    }}
    function copyPath(path) {{
      navigator.clipboard.writeText(path)
        .then(function() {{
          showStatus('Copied path to clipboard.');
        }})
        .catch(function(err) {{
          showStatus('Copy failed: ' + err);
        }});
    }}
    function setDrag(ev, fileUrl, filePath, fileName) {{
      ev.dataTransfer.setData('text/uri-list', fileUrl);
      ev.dataTransfer.setData('text/plain', filePath);
      ev.dataTransfer.effectAllowed = 'copy';
      showStatus('Dragging: ' + fileName);
    }}
    function selectedCheckboxes(tableKind) {{
      return Array.prototype.slice.call(document.querySelectorAll('input.file-select[data-table=\"' + tableKind + '\"]:checked'));
    }}
    function setSelectionForTable(tableKind, value) {{
      var boxes = document.querySelectorAll('input.file-select[data-table=\"' + tableKind + '\"]');
      boxes.forEach(function(cb) {{
        cb.checked = value;
      }});
      showStatus((value ? 'Selected ' : 'Cleared ') + boxes.length + ' files in ' + tableKind + '.');
    }}
    function setBulkDrag(ev, tableKind) {{
      var selected = selectedCheckboxes(tableKind);
      if (!selected.length) {{
        ev.preventDefault();
        showStatus('Select one or more files first.');
        return;
      }}
      var urls = selected.map(function(cb) {{ return cb.dataset.fileUrl; }});
      var paths = selected.map(function(cb) {{ return cb.dataset.filePath; }});
      var names = selected.map(function(cb) {{ return cb.dataset.fileName; }});
      ev.dataTransfer.setData('text/uri-list', urls.join('\\r\\n'));
      ev.dataTransfer.setData('text/plain', paths.join('\\n'));
      ev.dataTransfer.effectAllowed = 'copy';
      showStatus('Dragging ' + selected.length + ' files: ' + names.slice(0, 3).join(', ') + (names.length > 3 ? ' ...' : ''));
    }}
    document.addEventListener('click', function(ev) {{
      var btn = ev.target.closest('button.open-file-link');
      if (!btn) {{
        return;
      }}
      var fileUrl = btn.getAttribute('data-file-url') || '';
      if (!fileUrl) {{
        showStatus('Open failed: missing file URL.');
        return;
      }}
      openFileLink(fileUrl);
    }});
  </script>
</body>
</html>"""


def make_handler(engine_path: str, libraries: List[str], active_model: str, batch_size: int):
    can_use_open_cmd = shutil.which("open") is not None
    container_library_root = os.environ.get("CONTAINER_LIBRARY_ROOT", "/books").rstrip("/")
    host_library_root = os.environ.get("HOST_LIBRARY_ROOT", "").rstrip("/")

    def host_visible_path(path: str) -> str:
        if host_library_root and path.startswith(container_library_root + "/"):
            return host_library_root + path[len(container_library_root):]
        return path

    def attach_actions(library_path: str, rows: List[Dict]) -> None:
        book_map = resolve_book_open_paths(library_path, [r["book_id"] for r in rows])
        for row in rows:
            file_info = book_map.get(int(row["book_id"]))
            if not file_info:
                row["actions_html"] = ""
                continue
            abs_path = file_info["path"]
            visible_path = host_visible_path(abs_path)
            file_name = os.path.basename(visible_path)
            file_url = "file://" + urllib.parse.quote(visible_path)
            open_url = (
                "/open?library="
                + urllib.parse.quote(library_path, safe="")
                + "&book_id="
                + str(row["book_id"])
            )
            reveal_url = open_url + "&action=reveal"
            js_open = html.escape(json.dumps(open_url), quote=True)
            js_reveal = html.escape(json.dumps(reveal_url), quote=True)
            js_path = html.escape(json.dumps(visible_path), quote=True)
            js_file_url = html.escape(json.dumps(file_url), quote=True)
            js_file_name = html.escape(json.dumps(file_name), quote=True)
            data_file_url = html.escape(file_url, quote=True)
            data_file_path = html.escape(visible_path, quote=True)
            data_file_name = html.escape(file_name, quote=True)
            table_kind = "semantic-results" if "chunk_hits" in row else "tag-results"
            if can_use_open_cmd:
                action_controls = (
                    f'<button type="button" onclick="openFile({js_open})">Open</button> '
                    f'<button type="button" onclick="revealFile({js_reveal})">Reveal</button> '
                )
            else:
                action_controls = f'<button type="button" class="open-file-link" data-file-url="{data_file_url}">Open</button> '
            row["actions_html"] = (
                f'<label style="display:inline-flex;align-items:center;gap:4px;margin-right:8px;">'
                f'<input type="checkbox" class="file-select" data-table="{table_kind}" data-file-url="{data_file_url}" data-file-path="{data_file_path}" data-file-name="{data_file_name}" />'
                f'Select</label> '
                f'{action_controls}'
                f'<button type="button" onclick="copyPath({js_path})">Copy Path</button> '
                f'| <a href="{file_url}">File Link</a> '
                f'| <span draggable="true" ondragstart="setDrag(event, {js_file_url}, {js_path}, {js_file_name})" '
                f'style="cursor:grab;text-decoration:underline;font-weight:600">Drag File</span>'
            )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/open":
                if not can_use_open_cmd:
                    self.send_response(501)
                    self.end_headers()
                    self.wfile.write(b"open command is unavailable in this container. Use File Link or Drag File.")
                    return
                params = urllib.parse.parse_qs(parsed.query)
                library = params.get("library", [""])[0]
                book_id_raw = params.get("book_id", [""])[0]
                action = params.get("action", ["open"])[0]
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
                cmd = ["open", target]
                if action == "reveal":
                    cmd = ["open", "-R", target]
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                except FileNotFoundError:
                    self.send_response(501)
                    self.end_headers()
                    self.wfile.write(b"open command unavailable on this host.")
                    return
                if proc.returncode != 0:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write((proc.stderr.strip() or "open failed").encode("utf-8"))
                    return
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
                embedding_model="text-embedding-ada-002",
                top_k=50,
                query="",
                semantic_tag_expr="",
                tag_expr="",
                use_elbow=False,
                semantic_rows=[],
                tag_rows=[],
                semantic_error="",
                tag_error="",
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def do_POST(self):
            if self.path not in ("/search", "/search-tag"):
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = urllib.parse.parse_qs(raw)

            selected_library = data.get("library", [libraries[0]])[0]
            embedding_model = data.get("embedding_model", ["text-embedding-ada-002"])[0]
            query = data.get("query", [""])[0].strip()
            semantic_tag_expr = data.get("semantic_tag_expr", [""])[0].strip()
            tag_expr = data.get("tag_expr", [""])[0].strip()
            use_elbow = data.get("use_elbow", ["0"])[0] == "1"
            try:
                top_k = int(data.get("top_k", ["50"])[0])
                if top_k <= 0 or top_k > 200:
                    raise ValueError
            except ValueError:
                top_k = 50

            semantic_rows = []
            tag_rows = []
            semantic_error = ""
            tag_error = ""
            if selected_library not in libraries:
                selected_library = libraries[0]
                if self.path == "/search":
                    semantic_error = "Invalid library selection."
                else:
                    tag_error = "Invalid library selection."
            elif self.path == "/search":
                if not query:
                    semantic_error = "Enter a query."
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
                        semantic_rows = aggregate_results(raw_results)
                        tag_map = load_tags_for_books(selected_library, [int(r["book_id"]) for r in semantic_rows])
                        semantic_rows, _ = apply_tag_boolean_filter(semantic_rows, tag_map, semantic_tag_expr)
                        attach_actions(selected_library, semantic_rows)
                        if use_elbow:
                            semantic_rows = apply_elbow_cutoff(semantic_rows)
                    except Exception as exc:
                        semantic_error = str(exc)
            else:
                if not tag_expr:
                    tag_error = "Enter a boolean tag query."
                else:
                    try:
                        books = load_books_with_tags(selected_library, limit=10000)
                        tag_rows = [
                            {
                                "book_id": int(r["book_id"]),
                                "title": r.get("title", ""),
                                "author": r.get("author", ""),
                                "tag_hits": len(r.get("tags", [])),
                            }
                            for r in books
                        ]
                        tag_map = {int(r["book_id"]): r.get("tags", []) for r in books}
                        tag_rows, _ = apply_tag_boolean_filter(tag_rows, tag_map, tag_expr)
                        attach_actions(selected_library, tag_rows)
                    except Exception as exc:
                        tag_error = str(exc)

            page = render_page(
                libraries=libraries,
                selected_library=selected_library,
                embedding_model=embedding_model,
                top_k=top_k,
                query=query,
                semantic_tag_expr=semantic_tag_expr,
                tag_expr=tag_expr,
                use_elbow=use_elbow,
                semantic_rows=semantic_rows,
                tag_rows=tag_rows,
                semantic_error=semantic_error,
                tag_error=tag_error,
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
