"""Packages you installed on top of Omarchy.

Omarchy's own packages come from its package lists, its hardware scripts and
its omarchy-install-* commands. Anything explicitly installed and not from one
of those is yours. Packages an omarchy-install-* command brings are better
restored by running that command, so they become steps.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from ..env import Env, files_under, glob, item, split_lines
from ..omarchy import installs, package_list, pkg_args


def installed_at_install(env: Env) -> set[str]:
    """Packages the installer put down before first boot (kernel, sudo, microcode,
    bootloader tools). They are not in Omarchy's lists, so read them from the
    first two hours of pacman's log."""
    try:
        lines = split_lines(env.pacman_log.read_text("utf-8", "replace"))
    except OSError:
        return set()
    if not lines:
        return set()
    m = re.match(r"^\[([^]]*)\]", lines[0])
    if not m:
        return set()
    try:
        start = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return set()
    limit = start + 7200
    names = set()
    for line in lines:
        if "[ALPM] installed " not in line:
            continue
        fields = line.split()
        ts = re.sub(r"[+-][0-9]{4}$", "", fields[0][1:-1].replace("T", " "))
        try:
            t = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))  # local time, as date -d reads it
        except ValueError:
            continue
        if t > limit:
            break
        if len(fields) > 3:
            names.add(fields[3])
    return names


def installers(env: Env) -> dict[str, str]:
    """Package -> the omarchy-install-* command that installs it (first one wins)."""
    found: dict[str, str] = {}
    bin_dir = env.omarchy / "bin"
    for cmd in glob(bin_dir / "omarchy-install-*") + glob(bin_dir / "omarchy-*-install"):
        if not os.path.isfile(cmd):
            continue
        try:
            text = Path(cmd).read_text("utf-8", "replace")
        except OSError:
            continue
        for pkg in sorted(pkg_args(text)):
            found.setdefault(pkg, os.path.basename(cmd))
    return found


def setups(env: Env) -> dict[str, tuple[str, str]]:
    """Package -> (the omarchy-setup-* command that installs it, the name it
    installs). A setup can install a different build of a package (the
    fingerprint setup installs libfprint-git, which provides libfprint), so
    what each one provides counts too."""
    found: dict[str, tuple[str, str]] = {}
    for cmd in glob(env.omarchy / "bin" / "omarchy-setup-*"):
        try:
            text = Path(cmd).read_text("utf-8", "replace")
        except OSError:
            continue
        for pkg in sorted(installs(text)):
            found.setdefault(pkg, (os.path.basename(cmd), pkg))
    if found:
        name = ""
        for line in env.run("pacman", "-Si", *sorted(found)).lines():
            key, _, value = line.partition(":")
            key = key.strip()
            if key == "Name":
                name = value.strip()
            elif key == "Provides" and name in found and value.strip() != "None":
                for p in value.split():
                    found.setdefault(p.split("=")[0], found[name])
    return found


def in_aur(env: Env, pkgs: set[str]) -> dict[str, dict] | None:
    """What the AUR has on these packages, by name, in one request. None when
    offline or when the AUR does not answer, so nothing is judged on a guess."""
    if env.offline or not pkgs:
        return None
    url = "https://aur.archlinux.org/rpc/v5/info?" + "&".join(f"arg[]={quote(p)}" for p in sorted(pkgs))
    try:
        return {r["Name"]: r for r in json.loads(env.run("curl", "-sf", "--max-time", "15", url).out)["results"]}
    except (ValueError, KeyError, TypeError):
        return None


def pacman_info(env: Env, *flags: str) -> dict[str, dict]:
    """pacman -Qi output, by package name: version and description."""
    info: dict[str, dict] = {}
    current: dict = {}
    for line in env.run("pacman", "-Qi", *flags).lines():
        key, sep, value = line.partition(":")
        if not sep or line.startswith(" "):
            continue
        key, value = key.strip(), value.strip()
        if key == "Name":
            current = info.setdefault(value, {})
        elif key in ("Version", "Description"):
            current[key.lower()] = value
    return info


def collect(env: Env) -> list[dict]:
    o = env.omarchy
    base = set(package_list(o / "install/omarchy-base.packages"))
    # omarchy-base.packages is what the ISO installs. omarchy-other.packages only
    # lists what the ISO's offline mirror must hold, so it counts as Omarchy's but
    # its packages are not expected on every machine.
    lists = set()
    for f in glob(o / "install/*.packages"):
        lists.update(package_list(Path(f)))

    at_install = installed_at_install(env)
    install_text = "".join(Path(n.path).read_text("utf-8", "replace") for n in files_under(o / "install"))
    hardware = pkg_args(install_text)
    by_installer = installers(env)
    by_setup = setups(env)
    foreign = set(env.run("pacman", "-Qqm").lines())
    aur = in_aur(env, foreign)
    info = pacman_info(env, "-e")
    # Which sync repo each package comes from (omarchy, core, extra...). The first
    # repo in pacman.conf wins, as pacman itself picks.
    repo_of: dict[str, str] = {}
    for line in env.run("pacman", "-Sl").lines():
        parts = line.split()
        if len(parts) >= 2:
            repo_of.setdefault(parts[1], parts[0])

    items = []
    for pkg in env.run("pacman", "-Qqe").lines():
        if pkg in lists:
            continue
        source = "aur" if pkg in foreign else "pacman"
        facts = {"source": source, "version": info.get(pkg, {}).get("version", ""),
                 "description": info.get(pkg, {}).get("description", "")}
        if source == "pacman" and pkg in repo_of:
            facts["repo"] = repo_of[pkg]
        installer = by_installer.get(pkg)
        if installer:
            facts["installer"] = installer
        setup, setup_name = by_setup.get(pkg, ("", ""))
        if setup:
            facts["setup"] = setup
        if source == "aur" and aur is not None and pkg not in aur:
            facts["in_aur"] = False
        # Someone flagged it out of date: often a dependency moved on and the
        # build broke, which only shows on the new machine.
        if source == "aur" and (flagged := (aur or {}).get(pkg, {}).get("OutOfDate")):
            facts["aur_out_of_date"] = date.fromtimestamp(flagged).isoformat()

        if pkg in at_install:
            items.append(item("package", pkg, "skip", "Put down by the Omarchy installer before first boot.", facts))
        elif installer:
            items.append(item("package", pkg, "step", f"Omarchy installs this with {installer}. Run that instead of installing the package.", facts))
        elif pkg in hardware:
            items.append(item("package", pkg, "skip", "Omarchy installs this itself on hardware that needs it.", facts))
        elif setup:
            # Carrying it would fight the setup: Omarchy may pick another build.
            build = f" (as {setup_name}, which replaces it)" if setup_name != pkg else ""
            items.append(item("package", pkg, "skip", f"Omarchy's {setup} installs this{build} when you run it. "
                              "Run that on the new machine instead of carrying the package.", facts))
        elif facts.get("in_aur") is False:
            items.append(item("package", pkg, "note", "Not in the AUR, so the new machine cannot install it by name: "
                              "it was built here from source or came from a repo that is gone. Carry its source "
                              "repo and build it there, or leave it out.", facts))
        elif source == "aur" and "aur_out_of_date" in facts:
            items.append(item("package", pkg, "carry", f"Installed from the AUR, not part of Omarchy. Flagged out of "
                              f"date there since {facts['aur_out_of_date']}, so it may not build on a new machine: "
                              "bin/check-builds tells you before you rely on it.", facts))
        elif source == "aur":
            items.append(item("package", pkg, "carry", "Installed from the AUR, not part of Omarchy.", facts))
        else:
            items.append(item("package", pkg, "carry", "Installed by you from Omarchy's package repo, but not part of Omarchy's default install."
                              if facts.get("repo") == "omarchy" else "Installed by you, not part of Omarchy.", facts))

    # Omarchy defaults that are gone. Often deliberate, sometimes an accident.
    # pacman -T prints the ones nothing installed provides (a -git or -bin
    # variant counts as provided).
    if base:
        missing = env.run("pacman", "-T", *sorted(base)).lines()
        for pkg in missing:
            if pkg in hardware:
                continue
            items.append(item("package-removed", pkg, "review",
                              "In Omarchy's package list but not installed here. If you removed it on purpose, "
                              "the new machine needs the same removal.", {"source": "omarchy-list"}))
    return items
