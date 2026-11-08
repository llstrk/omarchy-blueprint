"""Config files in your home that differ from what Omarchy put there.

The baseline is /etc/skel (what a new user starts with) and Omarchy's config/
folder. A file that matches its default is left out. A file that differs, or
that Omarchy never shipped, is a candidate.

Folders Omarchy never shipped are judged by their contents: caches, databases
and browser profiles are app data and stay behind; small text files are
probably settings.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from ..omarchy import package_list
from ..env import (Env, files_under, glob, is_junk, is_text, item, mode_of, read_text,
                   same_file, size_under, split_lines, walk)
from ..git import git_facts
from .identity import CREDENTIAL_FILES

# Folders that hold app state, whatever is inside.
APP_STATE_CONFIG = (
    "chromium", "google-chrome", "google-chrome-beta", "google-chrome-unstable", "google-chrome-for-testing",
    "BraveSoftware", "vivaldi", "opera", "microsoft-edge", "microsoft-edge-dev", "Code", "Code - OSS", "VSCodium",
    "Cursor", "discord", "Slack", "Signal", "obsidian", "spotify", "1Password", "Bitwarden", "dconf", "pulse",
    "session", "ibus", "gnome-session", "evolution", "libreoffice", "Electron", "fcitx",
)

# Shell and tool settings that live directly in home.
HOME_RC = re.compile(r"^\.(bash_profile|profile|bash_aliases|inputrc|gitconfig|tmux\.conf|vimrc|editorconfig|"
                     r"Xresources|xprofile|ripgreprc|psqlrc|irbrc|gemrc|curlrc|wgetrc|nanorc|digrc|sqliterc|"
                     r"zshrc|zprofile|zshenv)$")

SETTINGS_NAMES = ("*.toml", "*.conf", "*.ini", "*.yaml", "*.yml", "settings.json", "config.json", "config")
STATEY_NAMES = ("Local Storage", "IndexedDB", "Cookies", "*.sqlite*", "*.db", "*.db-*", "*.ldb")


def in_list(path: str, roots) -> bool:
    return any(path == r or path.startswith(r + "/") for r in roots)


def state_reason(path: str, app_state) -> str:
    """Why a file is state rather than a setting, or ''."""
    if in_list(path, app_state):
        return "App data, not a setting."

    def any_of(*pats):
        return any(fnmatch.fnmatchcase(path, p) for p in pats)

    if any_of("*/logs/*", "*/log/*", "*.log", "*/profiler_data/*", "*/[Cc]ache/*", "*/*[Cc]ache*/*"):
        return "Logs or cache."
    if any_of("*/NativeMessagingHosts/*"):
        return "Written by a browser extension's installer."
    if any_of("*.pem", "*.key", "*.crt", "*.p12", "*token*", "*secret*", "*credential*", "*.age"):
        return "Looks like a key, certificate or credential."
    if any_of("*.tmp.*", "*.lock", "*.pid", "*/dbus/*"):
        return "Temporary or runtime file."
    name = os.path.basename(path)
    if any(fnmatch.fnmatchcase(name, p) for p in (".last-run*", "*.v[0-9]", "*.old", "*.prev", "state.*", "*history*")):
        return "State the app keeps for itself."
    return ""


def diff_lines(env: Env, a: str, b: str) -> int:
    """Lines that differ between two files, as diff counts them."""
    return sum(1 for line in env.run("diff", "--", a, b).lines() if line[:1] in ("<", ">"))


class Configs:
    def __init__(self, env: Env):
        self.env = env
        h = str(env.home)
        self.c = h + "/.config"
        self.per_machine = (self.c + "/hypr/monitors.lua", self.c + "/hypr/monitors.conf")
        # Handled by other collectors.
        self.owned_elsewhere = (
            self.c + "/omarchy/plugins",  # plugins
            self.c + "/systemd",  # services
            self.c + "/mise",  # tools
            self.c + "/gh",  # identity
            h + "/.local/share/applications",  # desktop entries, below
        ) + tuple(f"{h}/{c}" for c in CREDENTIAL_FILES)  # identity notes them: never carried
        self.app_state = tuple(f"{self.c}/{n}" for n in APP_STATE_CONFIG) + (h + "/.local/state", h + "/.local/share/nvim")
        # Paths tracked by Omarchy dots (mise history), if it is on.
        self.dots_tracked = {
            re.sub(r"^~", h, line.split()[0]) for line in env.run("mise", "dot", "paths").lines() if line.split()
        }
        # The apps every Omarchy install has. They write their own settings files
        # the first time they run, so those files are not in Omarchy's tree.
        self.default_apps = {p.lower() for p in package_list(env.omarchy / "install/omarchy-base.packages")}
        self.items: list[dict] = []

    def default_app(self, path: str) -> str:
        """The Omarchy default app a file under ~/.config is named after, or ''."""
        if not path.startswith(self.c + "/"):
            return ""
        parts = path[len(self.c) + 1:].split("/")
        names = [n.lower() for n in parts[:-1]] + [parts[-1].split(".")[0].lower()]
        return next((n for n in names if n in self.default_apps), "")

    def baseline(self, path: str) -> str:
        """The default copy of a file in home, or ''."""
        rel = path[len(str(self.env.home)) + 1:]
        if os.path.exists(self.env.skel / rel):
            return str(self.env.skel / rel)
        if rel.startswith(".config/") and os.path.exists(self.env.omarchy / "config" / rel[len(".config/"):]):
            return str(self.env.omarchy / "config" / rel[len(".config/"):])
        return ""

    def judge(self, f: str) -> None:
        env = self.env
        if is_junk(env, f) or in_list(f, self.owned_elsewhere):
            return
        base = self.baseline(f)
        facts = {"path": env.home_rel(f), "size": os.lstat(f).st_size, "mode": mode_of(f), "text": is_text(f)}
        if base:
            if same_file(f, base):
                return
            lines = diff_lines(env, base, f)
            reason = f"Edited from Omarchy's default ({lines} lines differ)."
            facts.update(default=base, lines_changed=lines)
        else:
            reason = "Not shipped by Omarchy."
        app = "" if base else self.default_app(f)
        if app:
            reason = f"Written by {app}, one of Omarchy's default apps, as you use it."

        state = state_reason(f, self.app_state)
        if state:
            cls = "note" if "credential" in state else "skip"
            reason = state
        elif not base and env.corpus.mentions(os.path.basename(os.path.dirname(f)) + "/" + os.path.basename(f)):
            cls = "review"
            reason = "Omarchy writes this file in an installer or migration. Carry it only if you changed it since."
        elif f in self.dots_tracked:
            cls = "skip"
            reason += " Omarchy dots already syncs it."
        elif in_list(f, self.per_machine):
            cls = "module:machine"
            reason += " Describes this machine's displays, so it belongs in a hardware module."
        elif not base and facts["size"] == 0:
            cls = "skip"
            reason += " Empty: the app writes it again when it needs to."
        elif not is_text(f):
            cls = "review"
            reason += " Binary or large: check it is a setting and not data."
        elif app:
            cls = "review"
            reason += " Carry it only if it holds choices you made, not window sizes or recent folders."
        elif base:
            cls = "carry"
        else:
            cls = "review"
            reason += " Small text file, probably a setting. Check it holds nothing private."
        self.items.append(item("config", env.home_rel(f), cls, reason, facts))

    def settings_in(self, d: str) -> list[str]:
        """Settings-looking files near the top of an app-data folder."""
        found = []
        for n in walk(d, maxdepth=2):
            if n.is_file and any(fnmatch.fnmatchcase(n.name, p) for p in SETTINGS_NAMES) and size_under(n.path, 64):
                found.append(n.path)
                if len(found) == 5:
                    break
        return found

    def collect(self) -> list[dict]:
        env, h, c = self.env, str(self.env.home), self.c
        skel, oconfig = env.skel, env.omarchy / "config"

        shipped_files = {n.rel(skel) for n in files_under(skel)} | {".config/" + n.rel(oconfig) for n in files_under(oconfig)}
        shipped_dirs = ({n.rel(skel) for n in walk(skel, maxdepth=2) if n.depth >= 1}
                        | {".config/" + n.rel(oconfig) for n in walk(oconfig, maxdepth=1) if n.depth == 1})

        # Every shipped config file, plus files you added next to one (in the same
        # folder, not below it, so a shipped browser folder does not pull in a profile).
        candidates = {f"{h}/{rel}" for rel in shipped_files}
        for rel in {r.rsplit("/", 1)[0] for r in shipped_files if "/" in r}:
            if in_list(f"{h}/{rel}", self.app_state):
                continue
            candidates.update(n.path for n in walk(f"{h}/{rel}", maxdepth=1) if n.is_file)
        # Everything below a shipped ~/.config folder (hooks, branding, defaults),
        # except app state, plugins and themes, which are judged on their own.
        pruned = (c + "/omarchy/plugins", c + "/omarchy/themes")
        for rel in shipped_dirs:
            if not re.match(r"^\.config/[^/]*$", rel):
                continue
            d = f"{h}/{rel}"
            if not os.path.isdir(d) or in_list(d, self.app_state):
                continue
            candidates.update(
                n.path for n in walk(d, maxdepth=5, prune=lambda n: n.name == ".git" or n.path in pruned)
                if n.is_file and size_under(n.path, 256))
        for f in sorted(candidates):
            if not os.path.isfile(f) or in_list(f, self.app_state):  # browser profiles, plugin caches
                continue
            self.judge(f)

        # ~/.XCompose is written at install with your name and email, so compare it
        # to that template with the identity lines left out.
        xcompose = f"{h}/.XCompose"
        if os.path.isfile(xcompose):
            skip = re.compile(r"^\s*(#|$)|^include |<Multi_key> <space> <[ne]>")
            extra = sum(1 for line in split_lines(read_text(xcompose)) if not skip.search(line))
            if extra > 0:
                self.items.append(item("config", "~/.XCompose", "carry", f"Has {extra} compose sequences beyond Omarchy's default.",
                                       {"path": "~/.XCompose", "text": True, "mode": "644"}))

        # Shell and tool rc files directly in home.
        for f in glob(f"{h}/.[!.]*"):
            if not os.path.isfile(f) or os.path.islink(f) or not HOME_RC.match(os.path.basename(f)):
                continue
            if self.baseline(f):
                continue
            self.judge(f)

        self.unshipped_dirs(shipped_dirs)
        self.themes()
        self.desktop_entries()
        return self.items

    def unshipped_dirs(self, shipped_dirs: set[str]) -> None:
        """Folders under ~/.config that Omarchy never shipped."""
        env, c = self.env, self.c
        for d in glob(c + "/*"):
            name = os.path.basename(d)
            if is_junk(env, d) or in_list(d, self.owned_elsewhere) or f".config/{name}" in shipped_dirs:
                continue
            if os.path.islink(d):
                self.items.append(item("config", env.home_rel(d), "review",
                                       f"A symlink to {os.readlink(d)}. Decide whether its target is carried.",
                                       {"path": env.home_rel(d)}))
                continue
            if os.path.isfile(d):
                continue  # files directly in ~/.config were judged above

            files = [n for n in walk(d) if n.is_file]
            if not files:
                continue
            du = env.run("du", "-sk", d).out.split()
            size = int(du[0]) if du and du[0].isdigit() else 0
            statey = any(fnmatch.fnmatchcase(n.name.lower(), "*cache*") or any(fnmatch.fnmatchcase(n.name, p) for p in STATEY_NAMES)
                         for n in walk(d))
            facts = {"path": env.home_rel(d), "dir": True, "files": len(files), "kb": size,
                     "sample": [n.rel(d) for n in files[:8]]}

            if in_list(d, self.app_state) or statey:
                self.items.append(item("config-dir", env.home_rel(d), "note",
                                       f"App data ({len(files)} files, {size} KB): caches, databases or sign-ins. "
                                       "Back it up separately if it matters.", facts))
                # App data folders often keep a settings file next to the state.
                for f in self.settings_in(d):
                    if state_reason(str(env.home) + "/x" + f[len(d):], self.app_state):
                        continue
                    self.judge(f)
            elif len(files) <= 25 and size <= 512:
                for n in walk(d, prune=lambda n: n.name == ".git"):
                    if n.is_file:
                        self.judge(n.path)
            else:
                self.items.append(item("config-dir", env.home_rel(d), "review",
                                       f"Not shipped by Omarchy, {len(files)} files and {size} KB. "
                                       "Pick the settings files out of it, if any.", facts))

    def themes(self) -> None:
        """Themes you installed. A theme from a git repo is cloned again; one
        without a repo is carried as a folder."""
        env = self.env
        for t in glob(self.c + "/omarchy/themes/*", dirs_only=True):
            if is_junk(env, t):
                continue
            if os.path.isdir(t + "/.git"):
                self.items.append(item("theme", os.path.basename(t), "carry", "An Omarchy theme from its own repo.",
                                       {**git_facts(env, t), "deploy": "git"}))
            elif os.path.islink(t):
                continue  # Omarchy links its built-in themes here
            else:
                self.items.append(item("config-dir", env.home_rel(t), "carry", "An Omarchy theme with no repo behind it.",
                                       {"path": env.home_rel(t), "dir": True}))

    def desktop_entries(self) -> None:
        """Desktop entries. ~/.local/share is where apps keep their data, and most
        entries here are written by something: Omarchy, its installers, a tool that
        rewrites them, or an app registering itself. Only entries nothing would
        write again are carried."""
        env, h = self.env, str(self.env.home)
        share = h + "/.local/share/"
        for f in glob(h + "/.local/share/applications/*.desktop"):
            if not os.path.isfile(f):
                continue
            name = os.path.basename(f)
            base = self.baseline(f)
            if not base and os.path.exists(env.omarchy / "applications" / name):
                base = str(env.omarchy / "applications" / name)
            if base and same_file(f, base):
                continue
            text = read_text(f)
            lines = split_lines(text)
            title, exec_line, icon = (entry_key(lines, k) for k in ("Name", "Exec", "Icon"))
            prog = first_word(exec_line)
            tool = os.path.basename(prog)
            facts = {"path": env.home_rel(f), "title": title, "exec": exec_line, "text": True, "mode": "644"}

            cls = "carry"
            if base and [x for x in split_lines(read_text(base)) if not x.startswith("Exec=")] == \
                    [x for x in lines if not x.startswith("Exec=")]:
                cls = "note"
                reason = (f"Omarchy's own entry, but {tool} rewrote how it launches. A new machine gets Omarchy's "
                          f"version, and {tool} changes it again when you set {tool} up there.")
                facts["rewritten_by"] = tool
            elif base:
                cls = "review"
                reason = "Omarchy's own entry, changed in more than how it launches. Carry it if you edited it on purpose."
            elif env.corpus.mentions(f'omarchy-webapp-install "{title}"') or tool.startswith("omarchy-launch-"):
                cls = "skip"
                reason = "Written by one of Omarchy's installers. Running that installer on the new machine writes it again."
                if not tool.startswith("omarchy-"):
                    reason += f" {tool} has since rewritten how it launches, and does that again once it is set up."
            elif any(x.startswith("MimeType=x-scheme-handler/") for x in lines) and any(x.startswith("NoDisplay=true") for x in lines):
                cls = "skip"
                reason = f"A link handler ({tool}) that the app registers itself the first time it runs."
            elif icon.startswith(share) or prog.startswith(share):
                owner = (icon if icon.startswith(share) else prog)[len(share):].split("/", 1)[0]
                cls = "skip"
                reason = f"Written by whatever installed ~/.local/share/{owner}. It comes back when that is installed again."
            elif prog.startswith(h + "/") and not os.path.exists(prog):
                cls = "skip"
                reason = f"Launches {prog}, which no longer exists."
            elif os.path.isabs(prog) and names_in_project(prog, name):
                cls = "skip"
                reason = f"Written by {tool} itself. It comes back when {tool} is installed and set up."
            else:
                reason = "A desktop entry nothing else writes. Carry it so the app shows up in the launcher."
            self.items.append(item("desktop-entry", env.home_rel(f), cls, reason, facts))


def entry_key(lines: list[str], key: str) -> str:
    for line in lines:
        if line.startswith(key + "="):
            return line[len(key) + 1:]
    return ""


def first_word(exec_line: str) -> str:
    """The program an Exec= line runs, without its quotes."""
    x = exec_line.removeprefix('"')
    return re.split(r'[" ]', x, maxsplit=1)[0]


def names_in_project(prog: str, needle: str) -> bool:
    """The project a program lives in (its bin/, lib/ and Python files) names the file."""
    top = os.path.join(os.path.dirname(prog), "..")
    roots = [os.path.join(top, "bin"), os.path.join(top, "lib")] + glob(top + "/*.py") + glob(top + "/*/*.py")
    data = needle.encode()
    for root in roots:
        for n in files_under(root):
            try:
                if data in Path(n.path).read_bytes():
                    return True
            except OSError:
                continue
    return False


def collect(env: Env) -> list[dict]:
    return Configs(env).collect()
