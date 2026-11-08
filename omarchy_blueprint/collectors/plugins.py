"""Omarchy shell plugins you added, and how each one should get to a new machine.

  git     a checkout of its own repo: clone it there (omarchy plugin add works too)
  rsync   a copy of a project's plugin/ folder: copy it from that project
  clone   cloned from a local checkout: clone it from that checkout
  copy    a plain folder: carry it as files, or better, give it its own repo
  link    a symlink: breaks hot reload, deploy a copy instead
"""

from __future__ import annotations

import fnmatch
import json
import os

from ..env import Env, files_under, glob, is_junk, item, walk
from ..git import git_facts


def plugin_id(manifest: str) -> str:
    """jq -r '.id // empty'."""
    try:
        data = json.loads(open(manifest, encoding="utf-8").read())
    except (OSError, ValueError):
        return ""
    value = data.get("id") if isinstance(data, dict) else None
    if value in (None, False):
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def jq_raw(value) -> str:
    """A value as jq -r prints it."""
    return value if isinstance(value, str) else json.dumps(value)


def collect(env: Env) -> list[dict]:
    h = str(env.home)
    plugins = h + "/.config/omarchy/plugins"
    if not os.path.isdir(plugins):
        return []

    r = env.run("omarchy", "plugin", "list", "--json")
    try:
        listing = json.loads(r.out) if r.ok else []
    except ValueError:
        listing = []

    # Projects with a plugin/ folder, by plugin id (first found wins).
    sources: dict[str, str] = {}
    for n in walk(h, maxdepth=4, prune=lambda n: n.path in (plugins, h + "/.cache")):
        if fnmatch.fnmatchcase(n.path, "*/plugin/manifest.json"):
            pid = plugin_id(n.path)
            if pid:
                sources.setdefault(pid, n.path[: -len("/plugin/manifest.json")])

    items = []
    for d in glob(plugins + "/*"):
        if not os.path.exists(d) or is_junk(env, d):
            continue
        pid = plugin_id(d + "/manifest.json") or os.path.basename(d)
        enabled = "\n".join(jq_raw(p.get("enabled")) for p in listing if isinstance(p, dict) and p.get("id") == pid)
        base = {"id": pid, "path": env.home_rel(d), "enabled": enabled or "unknown"}

        if os.path.islink(d):
            target = os.path.realpath(d)
            items.append(item("plugin", pid, "review",
                              f"A symlink to {env.home_rel(target)}. Omarchy's hot reload does not follow symlinks: "
                              "deploy a copy (rsync) from there instead.",
                              {**base, "deploy": "link", "source": env.home_rel(target)}))
        elif os.path.isdir(d + "/.git"):
            facts = {**base, **git_facts(env, d), "deploy": "git"}
            url = facts["url"]
            if url.startswith("/") or url.startswith("file://"):
                items.append(item("plugin", pid, "carry",
                                  f"Cloned from your checkout at {env.home_rel(url.removeprefix('file://'))}. "
                                  "Clone it from there after that repo is in place.", {**facts, "deploy": "clone"}))
            elif facts["reachable"] is False:
                items.append(item("plugin", pid, "review",
                                  f"Its repo ({url}) cannot be reached. Try to clone it in the bootstrap task and carry "
                                  "on if that fails, rather than listing it in [bootstrap.repos].", facts))
            else:
                items.append(item("plugin", pid, "carry", "A checkout of its own repo.", facts))
        elif pid in sources:
            src = env.home_rel(sources[pid]) + "/plugin"
            items.append(item("plugin", pid, "carry",
                              f"A copy of {src}. Deploy it from there with rsync, so edits go to the project.",
                              {**base, "deploy": "rsync", "source": src}))
        else:
            n = sum(1 for _ in files_under(d))
            items.append(item("plugin", pid, "review",
                              f"A plain folder ({n} files) with no repo behind it. Carry it as files, or give it its "
                              "own repo (one plugin per repo, manifest.json at the root).",
                              {**base, "deploy": "copy", "files": n}))
    return items
