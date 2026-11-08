"""Git facts for checkouts, and where the desktop refers to things."""

from __future__ import annotations

import os

from .env import Env, files_under, is_junk, read_text, size_under, walk


def git_facts(env: Env, path: str) -> dict:
    """Remote, branch, uncommitted changes, unpushed commits, and whether the remote answers."""
    def git(*args):
        return env.run("git", "-C", path, *args)

    url = git("remote", "get-url", "origin").out.strip()
    branch = git("symbolic-ref", "--short", "-q", "HEAD").out.strip()
    dirty = len(git("status", "--porcelain").lines())
    ahead_r = git("rev-list", "--count", "@{upstream}..HEAD")
    ahead = int(ahead_r.out.strip()) if ahead_r.ok and ahead_r.out.strip().isdigit() else None
    reachable = None
    if url and not env.offline and not url.startswith("/") and not url.startswith("file://"):
        r = env.run("git", "ls-remote", "--exit-code", url, "HEAD", timeout=15,
                    extra_env={"GIT_TERMINAL_PROMPT": "0",
                               "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=8"})
        reachable = r.ok
    return {"path": env.home_rel(path), "url": url, "branch": branch, "dirty": dirty,
            "ahead": ahead, "reachable": reachable}


def reference_text(env: Env) -> str:
    """Where the desktop refers to things: links in the command dirs, shell startup,
    Hyprland config, user units, autostart, Omarchy's own config and system units.
    A repo or file named here is something the desktop runs from."""
    h = str(env.home)
    parts = []
    for d in (h + "/.local/bin", h + "/bin"):
        if os.path.isdir(d):
            for n in walk(d, maxdepth=1):
                if n.is_link:
                    parts.append(f"{n.path} -> {os.readlink(n.path)}\n")
    for rc in (".bashrc", ".bash_profile", ".profile"):
        parts.append(read_text(f"{h}/{rc}"))
    plugins = h + "/.config/omarchy/plugins"
    for root in (".config/hypr", ".config/systemd/user", ".config/autostart", ".config/omarchy"):
        for n in walk(f"{h}/{root}", prune=lambda n: n.path == plugins):
            if n.is_file and size_under(n.path, 256) and not is_junk(env, n.path):
                parts.append(read_text(n.path))
    for n in files_under(env.etc / "systemd/system", maxdepth=1):
        parts.append(read_text(n.path))
    return "".join(parts).replace("$HOME", h).replace("~/", h + "/")
