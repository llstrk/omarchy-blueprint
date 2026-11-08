"""System files you changed or added under /etc.

Two kinds: package config files pacman reports as modified, and files no
package owns in the folders where people put system tweaks. Either is
Omarchy's when Omarchy's scripts name its path.
"""

from __future__ import annotations

import fnmatch
import os
import re

from ..env import Env, is_junk, is_text, item, mode_of, owner_of, shell_sorted, walk

# Where hand-made system tweaks live. Credentials folders are listed so they
# show up as notes, never carried.
DIRS = (
    "keyd", "udev/rules.d", "udev/hwdb.d", "systemd/system", "systemd/user",
    "systemd/logind.conf.d", "systemd/sleep.conf.d", "systemd/system.conf.d",
    "systemd/resolved.conf.d", "systemd/journald.conf.d", "systemd/network",
    "modprobe.d", "modules-load.d", "sysctl.d", "tmpfiles.d", "environment.d",
    "X11/xorg.conf.d", "pacman.d/hooks", "sudoers.d", "security/limits.d",
    "NetworkManager/conf.d", "NetworkManager/dispatcher.d", "docker", "profile.d",
    "fonts/conf.d", "xdg/autostart", "default",
)
# Set per machine by the installer or by tools (users, locale, disks).
MACHINE = re.compile(r"^/etc/(passwd|group|shadow|gshadow|shells|subuid|subgid|hostname|hosts|machine-id|"
                     r"locale\.gen|locale\.conf|vconsole\.conf|localtime|adjtime|fstab|crypttab|mkinitcpio\.conf|"
                     r"resolv\.conf|kernel/cmdline|updatedb\.conf)$")
CREDENTIALS = re.compile(r"^/etc/(sudoers\.d|NetworkManager/system-connections|ssh/ssh_host_|wireguard|ipsec|ppp/.*secrets)")


def modified_files(env: Env) -> list[tuple[str, str]]:
    """(package, /etc path) for every backup file pacman reports as [modified]."""
    found, pkg = [], ""
    for line in env.run("pacman", "-Qii").lines():
        if line.startswith("Name "):
            parts = line.split()
            pkg = parts[2] if len(parts) > 2 else ""
        if re.search(r"\[modified\]$", line):
            rest = re.sub(r"^Backup Files *: *", "", line).lstrip(" ")
            if rest.split():
                found.append((pkg, rest.split()[0]))
    return found


def collect(env: Env) -> list[dict]:
    items = []

    def emit(name: str, cls: str, reason: str, source: str, pkg: str) -> None:
        path = env.etc_path(name)
        readable = os.access(path, os.R_OK)
        owner, group = owner_of(path)
        facts = {"path": name, "source": source, "mode": mode_of(path), "owner": owner, "group": group,
                 "readable": readable, "text": readable and is_text(path)}
        if pkg:
            facts["package"] = pkg
        items.append(item("system-file", name, cls, reason, facts))

    def judge(name: str, source: str, pkg: str = "") -> None:
        what = f"Changed from what {pkg} installed." if source == "modified" else "No package owns it."
        override = env.omarchy / "etc-overrides" / name.removeprefix("/etc/").replace("/", "-")
        if MACHINE.search(name):
            emit(name, "skip", f"{what} The installer or a tool sets it for this machine.", source, pkg)
        elif CREDENTIALS.search(name):
            emit(name, "note", f"{what} Holds credentials or host identity, so it is never carried.", source, pkg)
        elif env.corpus.mentions(name) or "omarchy" in os.path.basename(name) or os.path.exists(override):
            emit(name, "skip", f"{what} Omarchy writes this file itself.", source, pkg)
        elif fnmatch.fnmatchcase(name, "/etc/ufw/*.rules"):
            emit(name, "review", f"{what} Firewall rules: Omarchy adds some itself. Compare with sudo ufw status, "
                 "and carry your own rules as ufw commands in a step rather than as files.", source, pkg)
        elif not os.access(env.etc_path(name), os.R_OK):
            emit(name, "review", f"{what} Only root can read it, so copy it into the repo by hand (sudo cat).", source, pkg)
        else:
            emit(name, "carry", what, source, pkg)

    # Package config files changed since install.
    for pkg, name in modified_files(env):
        if os.path.lexists(env.etc_path(name)):
            judge(name, "modified", pkg)

    # Files no package owns. Unit symlinks (enable/mask) are services, not files.
    owned = {line for line in env.run("pacman", "-Qlq").lines() if line.startswith("/etc/")}
    unowned = set()
    for d in DIRS:
        root = env.etc / d
        if root.is_dir():
            unowned.update(env.etc_name(n.path) for n in walk(root, maxdepth=2) if n.is_file)
    for name in shell_sorted(unowned - owned):
        if fnmatch.fnmatchcase(name, "*/*.wants/*") or fnmatch.fnmatchcase(name, "*/*.requires/*"):
            continue
        if is_junk(env, name):
            continue
        judge(name, "unowned")

    # Masked units are a choice too.
    for d in ("systemd/system", "systemd/user"):
        for n in walk(env.etc / d, maxdepth=1):
            if n.depth == 1 and n.is_link and os.readlink(n.path) == "/dev/null":
                if env.corpus.mentions_word(n.name):
                    continue
                items.append(item("masked-unit", n.name, "carry", "Masked: systemd will never start it.",
                                  {"path": env.etc_name(n.path)}))
    return items
