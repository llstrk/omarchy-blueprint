"""Build every AUR package a setup repo installs, and every PKGBUILD it pins
under pkgbuilds/, in throwaway folders without installing them. An AUR package
that built once can stop building when Arch updates something it needs, and
otherwise only a new machine finds out.

This runs the packages' build scripts, as the restore will, and asks sudo for
build dependencies that are missing (removed again afterwards). Run it on a
spare machine or a VM, or on the source machine when its owner agrees.

  bin/check-builds REPO
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

AUR = "https://aur.archlinux.org"
ERROR = re.compile(r"^ERROR|error:|Error:|not found")
# makepkg asks for the password again for every pacman call (sudo -k). Plain
# sudo asks once and remembers it for this terminal.
MAKEPKG_CONF = """source /etc/makepkg.conf
for c in /etc/makepkg.conf.d/*.conf; do [[ -r $c ]] && source "$c"; done
PACMAN_AUTH=(sudo)
"""


def aur_packages(repo: Path) -> list[str]:
    """The aur: packages in the repo's mise.toml and its module files."""
    names = set()
    for f in sorted(repo.glob("mise*.toml")):
        packages = tomllib.loads(f.read_text()).get("bootstrap", {}).get("packages", {})
        names |= {k.removeprefix("aur:") for k in packages if k.startswith("aur:")}
    return sorted(names)


def package_bases(names: list[str]) -> dict[str, str]:
    """The AUR repo is named after the package base, which differs for split packages."""
    query = urllib.parse.urlencode([("arg[]", n) for n in names])
    req = urllib.request.Request(f"{AUR}/rpc/v5/info?{query}", headers={"User-Agent": "omarchy-blueprint"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return {p["Name"]: p["PackageBase"] for p in json.load(r)["results"]}
    except (OSError, ValueError, KeyError):
        return {}


def error_lines(log: str) -> list[str]:
    lines = [line for line in log.splitlines()
             if ERROR.search(line) and not line.startswith("==> ERROR: A failure occurred")]
    return lines[-6:]


class Builder:
    def __init__(self, work: Path):
        self.work = work
        self.conf = work / "makepkg.conf"
        self.conf.write_text(MAKEPKG_CONF)
        self.failed: list[str] = []

    def build(self, name: str, folder: Path):
        log = self.work / f"{name}.log"
        print(f"  building {name} (sudo may ask, to install what the build needs)", flush=True)
        with open(log, "w") as out:
            rc = subprocess.run(["makepkg", "--config", str(self.conf), "--syncdeps", "--rmdeps", "--noconfirm"],
                                cwd=folder, stdout=out, stderr=subprocess.STDOUT).returncode
        if rc == 0:
            print(f"  ✓ {name} builds")
            shutil.rmtree(folder, ignore_errors=True)
            return
        print(f"  ✗ {name} does not build. Log: {log}")
        for line in error_lines(log.read_text(errors="replace")):
            print("      " + line)
        self.failed.append(name)

    def aur(self, names: list[str]):
        print("From the AUR:")
        bases = package_bases(names)
        for name in names:
            base = bases.get(name)
            if not base:
                print(f"  ✗ {name} is not in the AUR (or the AUR did not answer)")
                self.failed.append(name)
                continue
            folder = self.work / f"aur-{name}"
            if subprocess.run(["git", "clone", "-q", f"{AUR}/{base}.git", str(folder)],
                              capture_output=True).returncode != 0:
                print(f"  ✗ {name}: could not fetch {AUR}/{base}.git")
                self.failed.append(name)
                continue
            self.build(name, folder)

    def pinned(self, pkgbuilds: list[Path]):
        print("Pinned in pkgbuilds/:")
        for f in pkgbuilds:
            name = f.parent.name
            folder = self.work / f"pin-{name}"
            shutil.copytree(f.parent, folder)
            self.build(name, folder)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    repo = Path(argv[0]).resolve()
    if not (repo / "mise.toml").is_file():
        print(f"No setup repo at {repo} (it has no mise.toml).", file=sys.stderr)
        return 2
    names = aur_packages(repo)
    pinned = sorted(repo.glob("pkgbuilds/*/PKGBUILD"))
    if not names and not pinned:
        print(f"Nothing to build: no aur: packages and no pkgbuilds/ in {repo}.")
        return 0
    work = Path(tempfile.mkdtemp(prefix="check-builds."))
    b = Builder(work)
    if names:
        b.aur(names)
    if pinned:
        b.pinned(pinned)
    if not b.failed:
        shutil.rmtree(work, ignore_errors=True)
        print("Everything builds.")
        return 0
    print()
    print("These will not install on a new machine: " + " ".join(b.failed))
    print("The comments on an AUR package's page usually name the cause:")
    for name in b.failed:
        print(f"  {AUR}/packages/{name}")
    print('To pin a build that works, see "A package that no longer builds" in the repo\'s README.md.')
    return 1
