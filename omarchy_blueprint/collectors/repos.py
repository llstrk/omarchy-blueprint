"""Git checkouts in your home, and whether the desktop runs from them.

Only repos something on the desktop points at (a command link, Hyprland
config, a user unit, a deployed plugin) are carried. Development checkouts are
not: cloning every project onto every machine is slow, and a private repo you
cannot reach breaks the whole bootstrap.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from ..env import Env, cut_bytes, glob, is_junk, item, shell_sorted, split_lines, walk
from ..git import git_facts, reference_text

PRUNE = (".cache", ".local/share/Trash", ".local/share/mise", ".local/share/nvim", ".local/state", ".cargo",
         ".rustup", ".npm", ".bun", "go", "node_modules", ".config/omarchy/plugins", "snap", ".var")


def manifest_id(path: str) -> str:
    """jq -r .id: the id, "null" when it has none, "" when the file is not a JSON object."""
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return "" if not isinstance(data, type(None)) else "null"
    value = data.get("id")
    if value is None:
        return "null"
    return value if isinstance(value, str) else json.dumps(value)


def find_repos(env: Env) -> list[str]:
    h = str(env.home)
    pruned = {f"{h}/{p}" for p in PRUNE}
    repos = []
    for n in walk(h, maxdepth=4, prune=lambda n: n.path in pruned or n.name == "node_modules"):
        if n.name == ".git" and n.depth >= 1:
            repos.append(os.path.dirname(n.path))
    return shell_sorted(r for r in repos if r != h and not is_junk(env, r))


def collect(env: Env) -> list[dict]:
    refs = split_lines(reference_text(env))
    plugins = str(env.home) + "/.config/omarchy/plugins"
    repos = find_repos(env)
    with ThreadPoolExecutor(8) as pool:
        all_facts = list(pool.map(lambda r: git_facts(env, r), repos))

    items = []
    for repo, facts in zip(repos, all_facts):
        url = facts["url"]
        # What on the desktop points into this checkout.
        used_by = []
        hit = next((line for line in refs if repo + "/" in line), None)
        if hit is not None:
            used_by.append(cut_bytes(hit, 120))
        for p in glob(plugins + "/*", dirs_only=True):
            if not (os.path.isfile(repo + "/plugin/manifest.json") and os.path.isfile(p + "/manifest.json")):
                continue
            if manifest_id(repo + "/plugin/manifest.json") == manifest_id(p + "/manifest.json"):
                used_by.append(f"plugin {os.path.basename(p)} is deployed from its plugin/ folder")
            if env.run("git", "-C", p, "remote", "get-url", "origin").out.strip() == repo:
                used_by.append(f"plugin {os.path.basename(p)} is cloned from it")
        facts = {**facts, "used_by": used_by}
        name = env.home_rel(repo)

        risk = ""
        if not url:
            risk = "It has no remote, so it exists only on this machine."
        if facts["dirty"] != 0:
            risk += f" {facts['dirty']} uncommitted changes."
        if facts["ahead"] not in (0, None):
            risk += f" {facts['ahead']} commits not pushed."
        if facts["reachable"] is False:
            risk += " Its remote cannot be reached right now."
        risk = risk.removeprefix(" ")

        if used_by:
            if not url:
                items.append(item("repo", name, "review", "The desktop runs from it, but it has no remote. "
                                  "Push it somewhere first, or carry its files instead.", facts))
            elif facts["reachable"] is False:
                items.append(item("repo", name, "review", f"The desktop runs from it, but {url} cannot be reached. "
                                  f"Clone it in the bootstrap task so a failure does not stop the run. {risk}", facts))
            else:
                items.append(item("repo", name, "carry", f"The desktop runs from it. {risk}", facts))
        elif risk:
            items.append(item("repo", name, "note", f"A development checkout, not carried. {risk}", facts))
        else:
            items.append(item("repo", name, "skip", "A development checkout: nothing on the desktop runs from it. "
                              "Clone it by hand when needed.", facts))
    return items
