"""Logins, keys and enrollments: things that belong to this machine or to you and
can never be copied into a repo. Each becomes a guided step or a note. Only
names and counts are recorded, never contents.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re

from ..env import Env, item, read_text, split_lines, walk

CREDENTIAL_FILES = (".netrc", ".git-credentials", ".npmrc", ".pypirc", ".aws/credentials", ".kube/config",
                    ".docker/config.json", ".config/gh/hosts.yml", ".config/rclone/rclone.conf", ".config/restic")
PERSONAL = ("Documents", "Pictures", "Videos", "Music", "Downloads", "Desktop")


def collect(env: Env) -> list[dict]:
    h = str(env.home)
    items = []

    # SSH keys and client config.
    keys = [n.name for n in walk(h + "/.ssh", maxdepth=1)
            if n.depth == 1 and fnmatch.fnmatchcase(n.name, "id_*") and not fnmatch.fnmatchcase(n.name, "*.pub")]
    if keys:
        listed = " ".join(keys) + " "
        items.append(item("identity", "ssh-keys", "step", f"SSH keys ({listed}). Create a new key on the new machine, "
                          "or restore these from a backup. Never commit them.", {"keys": keys}))
    if os.path.isfile(h + "/.ssh/config"):
        hosts = sum(1 for line in split_lines(read_text(h + "/.ssh/config")) if re.match(r"^\s*host\s", line, re.I))
        items.append(item("identity", "ssh-config", "review", f"SSH client config with {hosts} host blocks. It has no "
                          "keys, but names hosts and users: carry it only in a private repo.",
                          {"path": "~/.ssh/config", "text": True, "mode": "600"}))

    # GitHub.
    gh = env.which("gh")
    if gh and env.run("gh", "auth", "token", "--hostname", "github.com").ok:
        items.append(item("identity", "github", "step", "Signed in to GitHub with gh. Private repos need this before "
                          "they can clone, so it comes first.", {"via": gh}))

    # Tailscale.
    if env.which("tailscale"):
        try:
            state = json.loads(env.run("tailscale", "status", "--json").out).get("BackendState") or ""
        except (ValueError, AttributeError):
            state = ""
        # Signing in waits on a browser, so the restore never runs it: the step
        # lists tailscale up for afterwards.
        items.append(item("identity", "tailscale", "step", f"Tailscale ({state or 'not running'}). A new machine joins "
                          "as a new device: the restore lists sudo tailscale up for afterwards. Never copy "
                          "/var/lib/tailscale.", {"state": state}))

    # Fingerprints.
    if env.which("fprintd-list") and " - #" in env.run("fprintd-list", env.user).out:
        items.append(item("identity", "fingerprint", "step", "Fingerprints are enrolled. Enrollment is per reader: "
                          "enroll again on the new machine.", {}))

    # Wi-Fi and VPN connections hold passwords.
    if env.which("nmcli"):
        n = sum(1 for line in env.run("nmcli", "-t", "-f", "TYPE", "connection", "show").lines()
                if re.search(r"wireless|vpn|wireguard", line))
        if n > 0:
            items.append(item("identity", "network-connections", "note", f"{n} Wi-Fi or VPN connections. Their "
                              "passwords are not carried: join them again.", {"count": n}))

    # GPG secret keys.
    if env.which("gpg"):
        n = sum(1 for line in env.run("gpg", "-K", "--with-colons").lines() if line.startswith("sec"))
        if n > 0:
            items.append(item("identity", "gpg-keys", "note", f"{n} GPG secret keys. Export them to a backup by hand, "
                              "never to the repo.", {"count": n}))

    # Credential files, by name only.
    for f in CREDENTIAL_FILES:
        if os.path.exists(f"{h}/{f}"):
            items.append(item("credential", f"~/{f}", "note", "Holds credentials. Sign in again on the new machine "
                              "instead of copying it.", {"path": f"~/{f}"}))

    # Personal data folders: sizes only, so the plan can point at a real backup.
    for d in PERSONAL:
        if not os.path.isdir(f"{h}/{d}"):
            continue
        # du on a large folder is slow, so give up after a few seconds and say so.
        out = env.run("du", "-sk", f"{h}/{d}", timeout=4).out.split()
        if out and out[0].isdigit():
            kb = int(out[0])
            size = f"{kb // 1024} MB"
        else:
            kb, size = 0, "large"
        if size != "large" and kb <= 64:
            continue
        items.append(item("personal-data", f"~/{d}", "note", f"Personal files ({size}). Use a backup (restic, a synced "
                          "drive), not this repo.", {"path": f"~/{d}", "kb": kb}))
    return items
