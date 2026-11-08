"""A fake Omarchy machine in a temporary folder, for testing rules without a real install."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from omarchy_blueprint.env import Env, Result


class Machine:
    """Files go under a temporary root; commands answer from a table.

    run(argv) looks up the longest matching argv prefix in self.commands.
    Anything not listed fails with no output, like a missing command.
    """

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home/me"
        self.omarchy = self.root / "omarchy"
        self.skel = self.root / "skel"
        self.etc = self.root / "etc"
        for d in (self.home, self.omarchy / "bin", self.omarchy / "install", self.omarchy / "config",
                  self.omarchy / "applications", self.skel, self.etc, self.root / "usr/bin"):
            d.mkdir(parents=True, exist_ok=True)
        self.commands: dict[tuple, tuple[int, str]] = {}
        self.calls: list[list[str]] = []
        self.which = {"git": "/usr/bin/git", "pacman": "/usr/bin/pacman", "systemctl": "/usr/bin/systemctl"}

    def close(self):
        self._tmp.cleanup()

    def write(self, path: Path | str, text: str = "", mode: int | None = None) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if mode is not None:
            p.chmod(mode)
        return p

    def link(self, path: Path | str, target: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, p)
        return p

    def answer(self, *argv: str, out: str = "", rc: int = 0) -> None:
        self.commands[tuple(argv)] = (rc, out)

    def run(self, argv, timeout=None, extra_env=None) -> Result:
        self.calls.append(argv)
        for n in range(len(argv), 0, -1):
            hit = self.commands.get(tuple(argv[:n]))
            if hit:
                return Result(*hit)
        return Result(1, "")

    def env(self, **kw) -> Env:
        kw.setdefault("offline", True)
        return Env(home=self.home, omarchy=self.omarchy, user="me", cache=self.root / "cache", skel=self.skel,
                   etc=self.etc, dmi=self.root / "dmi", cpuinfo=self.root / "cpuinfo",
                   pacman_log=self.root / "pacman.log", runner=self.run, which_paths=self.which, **kw)
