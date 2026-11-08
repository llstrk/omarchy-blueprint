"""Services you enabled, system and user.

A unit counts as yours when it is enabled although its vendor preset says
otherwise, and Omarchy's scripts never name it. Template units and units
Omarchy enables are left out.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from ..env import Env, is_junk, item, walk


def enabled_units(env: Env, ctl: list[str]) -> list[tuple[str, str]]:
    """(unit, preset) for every enabled unit file, in systemctl's order."""
    units = []
    for line in env.run(*ctl, "list-unit-files", "--state=enabled", "--no-legend").lines():
        fields = line.split()
        if fields:
            units.append((fields[0], fields[2] if len(fields) > 2 else ""))
    return units


def also_parents(env: Env, ctl: list[str], units: list[str]) -> dict[str, str]:
    """Units another enabled unit pulls in through Also= (NetworkManager brings its
    dispatcher, resolved brings its sockets). They follow their parent."""
    with ThreadPoolExecutor(8) as pool:
        texts = list(pool.map(lambda u: env.run(*ctl, "cat", u).lines(), units))
    parents: dict[str, str] = {}
    for unit, lines in zip(units, texts):
        for line in lines:
            if line.startswith("Also="):
                for child in line[len("Also="):].split(" "):
                    if child:
                        parents.setdefault(child, unit)
    return parents


def unit_props(env: Env, ctl: list[str], units: list[str]) -> list[dict]:
    """FragmentPath, ActiveState and Type for each unit, in order."""
    if not units:
        return []
    out = env.run(*ctl, "show", "-p", "FragmentPath", "-p", "ActiveState", "-p", "Type", "--", *units).out
    blocks = [b for b in out.split("\n\n")]
    props = []
    for i in range(len(units)):
        block = blocks[i] if i < len(blocks) else ""
        d = {}
        for line in block.split("\n"):
            key, sep, value = line.partition("=")
            if sep:
                d[key] = value
        props.append(d)
    return props


def scan(env: Env, scope: str) -> list[dict]:
    ctl = ["systemctl"] + (["--user"] if scope == "user" else [])
    listing = enabled_units(env, ctl)
    also = also_parents(env, ctl, [u for u, _ in listing])
    wanted = [(u, p) for u, p in listing if "@." not in u]
    props = unit_props(env, ctl, [u for u, _ in wanted])
    h = str(env.home) + "/"
    items = []
    for (unit, preset), prop in zip(wanted, props):
        fragment = prop.get("FragmentPath", "")
        active = prop.get("ActiveState", "")
        where = "local" if fragment.startswith("/etc/") or fragment.startswith(h) else "package"
        # A packaged unit its preset enables is the distribution's default. User
        # units have no preset rules, so for a unit you wrote the preset says nothing.
        if preset == "enabled" and (where == "package" or scope == "system"):
            continue
        pkg = ""
        if where == "package" and fragment:
            owners = env.run("pacman", "-Qqo", fragment).lines()
            pkg = owners[0] if owners else ""
        facts = {"scope": scope, "unit": unit, "unit_file": fragment, "unit_from": where, "active": active}
        if pkg:
            facts["package"] = pkg
        name = unit.rsplit(".", 1)[0] if "." in unit else unit
        if unit in also:
            items.append(item("service", unit, "skip", f"Enabled along with {also[unit]}.", facts))
        elif env.corpus.mentions_word(name) or env.corpus.mentions_word(unit):
            items.append(item("service", unit, "skip", "Omarchy enables this itself.", facts))
        elif unit.endswith(".service") and active != "active" and prop.get("Type") == "oneshot":
            items.append(item("service", unit, "carry", 'Enabled by you. A oneshot unit: enable it for boot without '
                              'starting it on every run (state = "stopped").', facts))
        else:
            items.append(item("service", unit, "carry", "Enabled by you.", facts))
    return items


def collect(env: Env) -> list[dict]:
    items = scan(env, "system") + scan(env, "user")
    # User units you wrote. They go in bootstrap.files, not dotfiles, so they
    # exist before the services step starts them.
    for n in walk(env.home / ".config/systemd/user", maxdepth=1):
        if n.depth != 1 or not n.is_file or is_junk(env, n.path):
            continue
        rel = env.home_rel(n.path)
        if env.corpus.mentions(n.name):
            items.append(item("user-unit", rel, "skip", "Written by an Omarchy installer.", {"path": rel}))
        else:
            items.append(item("user-unit", rel, "carry", "A user unit you wrote.", {"path": rel, "text": True, "mode": "644"}))
    return items
