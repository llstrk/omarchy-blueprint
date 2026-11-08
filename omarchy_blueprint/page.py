"""Show the inventory as a page you can review, and save your decisions.

  bin/blueprint [--out DIR] [--no-open]   serve the page until you press Done
  bin/blueprint --static [--out DIR]      write DIR/blueprint.html instead

Reads DIR/inventory.json (from bin/inspect) and DIR/decisions.json if it
exists. By default the page is served on this machine only (127.0.0.1, a
random port and a secret path), every choice is saved to DIR/decisions.json as
you make it, and the command ends when you press Done. With --static it is a
local file, and "Save decisions" downloads the file instead. Nothing is
uploaded either way. It uses the colors of your current Omarchy theme.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

KIT = Path(__file__).resolve().parent.parent

# Omarchy theme keys -> the CSS variables the page uses.
THEME_VARS = {
    "background": "bg", "dark_background": "bg-dark", "lighter_background": "bg-light", "selection": "sel",
    "muted": "muted", "foreground": "fg", "dark_foreground": "fg-dim", "bright_foreground": "fg-bright",
    "accent": "accent", "red": "red", "yellow": "yellow", "green": "green", "cyan": "cyan",
    "magenta": "magenta", "orange": "orange",
}


def embed(data) -> str:
    """JSON for a <script> tag, which must not contain "</"."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def theme_css(home: Path) -> str:
    for p in (home / ".local/state/omarchy/current/theme/colors.toml", home / ".config/omarchy/current/theme/colors.toml"):
        if p.is_file():
            try:
                colors = tomllib.loads(p.read_text())
            except (tomllib.TOMLDecodeError, OSError):
                return ""
            return "".join(f"--{THEME_VARS[key]}: {value}; " for key, value in colors.items()
                           if key in THEME_VARS and isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]+", value))
    return ""


def render(inventory: dict, decisions, theme: str, served: bool = False) -> str:
    page = (KIT / "blueprint/index.html").read_text()
    for marker, value in (("/*INVENTORY*/", embed(inventory)), ("/*DECISIONS*/", embed(decisions)),
                          ("/*SERVED*/", embed(served)), ("/*THEME*/", theme)):
        page = page.replace(marker, value, 1)
    return page


def load(out: Path) -> tuple[dict, dict | None]:
    dec = out / "decisions.json"
    return json.loads((out / "inventory.json").read_text()), (json.loads(dec.read_text()) if dec.is_file() else None)


def make_server(out: Path, theme: str, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """A server for the page on 127.0.0.1 only. The secret path keeps other
    pages in the browser from reading it or saving to it."""
    token = secrets.token_urlsafe(16)
    base = f"/{token}/"
    writing = threading.Lock()  # saves can arrive on several connections at once

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet: the agent reads this output
            pass

        def reply(self, code: int, body: bytes = b"", kind: str = "text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlsplit(self.path).path != base:
                return self.reply(404, b"Not here.")
            inventory, decisions = load(out)  # a reload shows what is saved
            self.reply(200, render(inventory, decisions, theme, served=True).encode(), "text/html; charset=utf-8")

        def do_POST(self):
            url = urlsplit(self.path)
            if url.path != base + "decisions":
                return self.reply(404, b"Not here.")
            # Only the page sends JSON: a form on another site cannot.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, b"JSON only.")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 20_000_000)))
                inventory, _ = load(out)
                if not isinstance(body.get("decisions"), dict) or body.get("inventory") != inventory.get("generated"):
                    raise ValueError("these decisions are for another inspection")
            except (ValueError, AttributeError, OSError) as e:
                return self.reply(400, f"Not saved: {e}".encode())
            with writing:
                tmp = out / "decisions.json.tmp"
                tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
                os.replace(tmp, out / "decisions.json")
            self.reply(204)
            if url.query == "done":
                self.server.done = True
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    # A thread per connection: browsers open spare connections that send
    # nothing, which would hold up a server that takes one at a time.
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.done = False
    return server, f"http://127.0.0.1:{server.server_port}{base}"


def open_in_browser(url: str) -> None:
    opener = shutil.which("omarchy-launch-browser") or shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bin/blueprint", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(KIT / "out"))
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--static", action="store_true", help="write blueprint.html instead of serving the page")
    args = ap.parse_args(argv)

    out = Path(args.out)
    inv = out / "inventory.json"
    if not inv.is_file():
        print(f"No {inv} yet. Run bin/inspect first.", file=sys.stderr)
        return 1
    theme = theme_css(Path(os.environ.get("HOME", Path.home())))

    if args.static:
        page = out / "blueprint.html"
        page.write_text(render(*load(out), theme))
        print(f"Wrote {page.resolve()}")
        if not args.no_open:
            open_in_browser(f"file://{page.resolve()}")
        return 0

    server, url = make_server(out, theme)
    print(f"The blueprint is at {url}", flush=True)
    print(f"Every choice is saved to {(out / 'decisions.json').resolve()} as it is made.", flush=True)
    print("Waiting for Done in the page (Ctrl-C stops early; choices so far stay saved).", flush=True)
    if not args.no_open:
        open_in_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped before Done.")
        return 130
    finally:
        server.server_close()
    _, decisions = load(out)
    d = (decisions or {}).get("decisions", {})
    yours = sum(1 for v in d.values() if v.get("by") == "you")
    print(f"Done: {len(d)} decisions, {yours} of them yours, in {(out / 'decisions.json').resolve()}")
    return 0
