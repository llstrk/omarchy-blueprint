"""Tools from mise and other language package managers.

mise's global config is carried as a whole: mise bootstrap installs its tools
at the end. Tools installed with npm, cargo, uv, pipx or bun are not recorded
anywhere a new machine can read, so they go to review with the mise backend
that would carry them (npm:, cargo:, pipx:).
"""

from __future__ import annotations

import json
import os
import re

from ..env import Env, glob, item


def collect(env: Env) -> list[dict]:
    h = str(env.home)
    items = []
    if os.path.isfile(h + "/.config/mise/config.toml"):
        r = env.run("mise", "ls", "--global", "--json")
        tools = []
        try:
            for tool, versions in (json.loads(r.out) if r.ok else {}).items():
                requested = (versions[0].get("requested_version") if versions else None) or "latest"
                tools.append({"tool": tool, "requested": requested})
        except (ValueError, AttributeError):
            tools = []
        items.append(item("config", "~/.config/mise/config.toml", "carry",
                          f"mise's global config: {len(tools)} tools, installed at the end of mise bootstrap.",
                          {"path": "~/.config/mise/config.toml", "text": True, "mode": "644", "tools": tools}))

    for f in glob(h + "/.config/mise/conf.d/*.toml") + glob(h + "/.config/mise/miserc*.toml"):
        if not os.path.isfile(f):
            continue
        rel = env.home_rel(f)
        if re.fullmatch(r"miserc.*\.toml", os.path.basename(f)):
            items.append(item("config", rel, "skip", "Per-machine mise settings (which modules this machine uses). "
                              "The bootstrap script writes it.", {"path": rel}))
        elif os.path.islink(f):
            items.append(item("config", rel, "skip", "A link Omarchy or a tool manages.", {"path": rel}))
        else:
            items.append(item("config", rel, "review", "Extra mise config. miserc.local.toml is per machine and should "
                              "stay that way.", {"path": rel, "text": True, "mode": "644"}))

    def outside(manager: str, backend: str, names) -> None:
        for name in names:
            if name:
                items.append(item("tool", f"{manager}:{name}", "review", f'Installed with {manager}, outside mise. '
                                  f'Add "{backend}:{name}" to mise\'s global tools to carry it.',
                                  {"manager": manager, "mise": f"{backend}:{name}"}))

    def words(lines) -> list[str]:
        return [w for line in lines for w in line.split()]

    if env.which("npm"):
        lines = env.run("npm", "ls", "-g", "--depth=0", "--parseable").lines()[1:]
        outside("npm", "npm", words(n for n in (re.sub(r".*/node_modules/", "", x) for x in lines)
                                    if n not in ("npm", "corepack")))
    if env.which("cargo"):
        outside("cargo", "cargo", words(m.group(1) for m in (re.match(r"^([^ ]*) v.*", x)
                                                               for x in env.run("cargo", "install", "--list").lines()) if m))
    if env.which("uv"):
        outside("uv", "pipx", words(m.group(1) for m in (re.match(r"^([^ -][^ ]*) v.*", x)
                                                           for x in env.run("uv", "tool", "list").lines()) if m))
    if env.which("pipx"):
        outside("pipx", "pipx", [x.split()[0] for x in env.run("pipx", "list", "--short").lines() if x.split()])
    bun = h + "/.bun/install/global/node_modules"
    if os.path.isdir(bun):
        outside("bun", "npm", sorted(n for n in os.listdir(bun) if not n.startswith(".")))
    return items
