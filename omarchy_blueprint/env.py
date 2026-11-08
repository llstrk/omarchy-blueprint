"""The machine as the inspector sees it, and helpers every collector shares.

Collectors never call subprocess or open system paths directly. They ask the
Env: env.run() for commands, env.etc / env.home / ... for paths. Tests build an
Env over a temporary tree with a fake runner, so every rule can be tested
without a real Omarchy install.
"""

from __future__ import annotations

import fnmatch
import functools
import grp
import locale
import os
import pwd
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator


@dataclass
class Result:
    rc: int
    out: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def lines(self) -> list[str]:
        return split_lines(self.out)


def split_lines(text: str) -> list[str]:
    """Lines the way grep and read see them: split on newlines, no trailing empty line."""
    if not text:
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def system_run(argv: list[str], timeout: float | None = None, extra_env: dict | None = None) -> Result:
    environ = dict(os.environ, **(extra_env or {}))
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=timeout, env=environ)
    except FileNotFoundError:
        return Result(127, "")
    except subprocess.TimeoutExpired:
        return Result(124, "")
    except OSError:
        return Result(126, "")
    return Result(p.returncode, p.stdout.decode("utf-8", "replace"))


@dataclass
class Env:
    home: Path
    omarchy: Path
    user: str
    cache: Path
    skel: Path = Path("/etc/skel")
    etc: Path = Path("/etc")
    dmi: Path = Path("/sys/class/dmi/id")
    cpuinfo: Path = Path("/proc/cpuinfo")
    pacman_log: Path = Path("/var/log/pacman.log")
    machine_arch: str = ""
    kernel: str = ""
    offline: bool = False
    runner: Callable[..., Result] = system_run
    which_paths: dict[str, str | None] | None = None  # tests: fixed answers for which()
    _corpus: object = field(default=None, repr=False)

    @classmethod
    def from_system(cls, offline: bool = False) -> "Env":
        home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
        omarchy = Path(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy")
        if not omarchy.is_dir():
            omarchy = home / ".local/share/omarchy"
        cache = Path(os.environ.get("BLUEPRINT_CACHE")
                     or Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / "omarchy-blueprint")
        u = os.uname()
        return cls(home=home, omarchy=omarchy, user=os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name,
                   cache=cache, offline=offline or os.environ.get("BLUEPRINT_OFFLINE") == "1",
                   machine_arch=u.machine, kernel=u.release)

    # Commands -----------------------------------------------------------

    def run(self, *argv: str, timeout: float | None = None, extra_env: dict | None = None) -> Result:
        return self.runner(list(argv), timeout=timeout, extra_env=extra_env)

    def which(self, name: str) -> str | None:
        if self.which_paths is not None:
            return self.which_paths.get(name)
        return shutil.which(name)

    # Paths --------------------------------------------------------------

    def etc_path(self, name: str) -> Path:
        """The real path of an /etc/... name (env.etc is /etc except in tests)."""
        return self.etc / name.removeprefix("/etc/")

    def etc_name(self, path: Path | str) -> str:
        return "/etc/" + os.path.relpath(path, self.etc)

    def home_rel(self, path: Path | str) -> str:
        """~/path for display. Paths outside home keep their full form after ~/."""
        p = str(path)
        prefix = str(self.home) + "/"
        return "~/" + (p[len(prefix):] if p.startswith(prefix) else p)

    def expand(self, name: str) -> Path:
        """~/x -> home/x."""
        return self.home / name[2:] if name.startswith("~/") else Path(name)

    @property
    def corpus(self):
        if self._corpus is None:
            from .omarchy import Corpus
            self._corpus = Corpus(self)
        return self._corpus


# Items -------------------------------------------------------------------

CLASSES = ("carry", "module", "step", "note", "skip", "review")


def item(kind: str, name: str, cls: str, reason: str, facts: dict | None = None) -> dict:
    """One finding. cls is carry, step, note, skip, review, or module:<name>."""
    module = None
    if cls.startswith("module:"):
        cls, module = "module", cls.split(":", 1)[1]
    assert cls in CLASSES, cls
    return {"id": f"{kind}:{name}", "kind": kind, "name": name, "class": cls,
            "module": module, "reason": reason, "facts": facts or {}}


# Files -------------------------------------------------------------------

JUNK = ("*.bak", "*.bak.*", "*.bak-*", "*~", "*.orig", "*.rej", "*.swp", "*-backup.*", ".DS_Store", ".git")


def is_junk(env: Env, path: Path | str) -> bool:
    """Backups and editor droppings: any part of the path below home matches."""
    p = str(path)
    prefix = str(env.home) + "/"
    if p.startswith(prefix):
        p = p[len(prefix):]
    return any(fnmatch.fnmatchcase(part, pat) for part in p.split("/") for pat in JUNK)


def is_text(path: Path | str) -> bool:
    """A regular file under 256 KiB with no binary content and at least one character."""
    try:
        if not os.path.isfile(path) or os.lstat(path).st_size >= 262144:
            return False
        data = Path(path).read_bytes()
    except OSError:
        return False
    return looks_text(data)


def looks_text(data: bytes) -> bool:
    """What grep -I . accepts: no NUL, valid UTF-8, and a line with a character in it."""
    if b"\0" in data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return any(line for line in text.split("\n"))


def read_text(path: Path | str) -> str:
    try:
        return Path(path).read_text("utf-8", "replace")
    except OSError:
        return ""


def same_file(a: Path | str, b: Path | str) -> bool:
    try:
        return Path(a).read_bytes() == Path(b).read_bytes()
    except OSError:
        return False


def mode_of(path: Path | str) -> str:
    """Permissions as stat -c %a prints them (644, 600, 4755)."""
    return format(stat.S_IMODE(os.lstat(path).st_mode), "o")


def owner_of(path: Path | str) -> tuple[str, str]:
    st = os.lstat(path)
    try:
        user = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        user = "UNKNOWN"
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = "UNKNOWN"
    return user, group


def size_under(path: Path | str, kib: int) -> bool:
    """find -size -Nk: the size in KiB, rounded up, is below N."""
    try:
        size = os.stat(path).st_size
    except OSError:
        return False
    return -(-size // 1024) < kib


# Walking -----------------------------------------------------------------

class Node:
    """A path found by walk(), typed the way find sees it."""

    __slots__ = ("path", "depth", "_st", "follow")

    def __init__(self, path: str, depth: int, st: os.stat_result, follow: bool):
        self.path, self.depth, self._st, self.follow = path, depth, st, follow

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def is_dir(self) -> bool:
        return stat.S_ISDIR(self._st.st_mode)

    @property
    def is_file(self) -> bool:
        return stat.S_ISREG(self._st.st_mode)

    @property
    def is_link(self) -> bool:
        return stat.S_ISLNK(self._st.st_mode)

    @property
    def size(self) -> int:
        return self._st.st_size

    def rel(self, root: Path | str) -> str:
        return os.path.relpath(self.path, root)


def _stat(path: str, follow: bool) -> os.stat_result | None:
    try:
        return os.stat(path) if follow else os.lstat(path)
    except OSError:
        if follow:
            try:
                return os.lstat(path)  # a broken link, as find -L reports it
            except OSError:
                return None
        return None


def walk(root: Path | str, *, maxdepth: int | None = None, follow: bool = False,
         prune: Callable[[Node], bool] | None = None) -> Iterator[Node]:
    """Every path under root in find's order: depth first, directory order, root first.

    follow=True is find -L. prune(node) returning True drops the node and,
    for a directory, everything below it (find's -prune ... -o).
    """
    root = str(root)
    st = _stat(root, follow)
    if st is None:
        return
    yield from _visit(Node(root, 0, st, follow), maxdepth, follow, prune, frozenset())


def _visit(node: Node, maxdepth, follow, prune, ancestors) -> Iterator[Node]:
    if prune and prune(node):
        return
    yield node
    if not node.is_dir or (maxdepth is not None and node.depth >= maxdepth):
        return
    key = (node._st.st_dev, node._st.st_ino)
    if key in ancestors:  # a symlink loop under follow=True
        return
    try:
        with os.scandir(node.path) as it:
            entries = [e.path for e in it]
    except OSError:
        return
    for path in entries:
        st = _stat(path, follow)
        if st is not None:
            yield from _visit(Node(path, node.depth + 1, st, follow), maxdepth, follow, prune, ancestors | {key})


def files_under(root: Path | str, **kw) -> Iterator[Node]:
    return (n for n in walk(root, **kw) if n.is_file)


@functools.cache
def _collation_ready() -> bool:
    try:
        locale.setlocale(locale.LC_COLLATE, "")
        return True
    except locale.Error:
        return False


def shell_sorted(paths) -> list:
    """Sort the way a shell glob does: by the locale's collation."""
    if _collation_ready():
        return sorted(paths, key=lambda p: locale.strxfrm(str(p)))
    return sorted(paths, key=str)


def glob(pattern: Path | str, dirs_only: bool = False) -> list[str]:
    """A shell glob: hidden names only when the pattern asks, sorted by collation."""
    import glob as _glob
    found = _glob.glob(str(pattern))
    if dirs_only:
        found = [p for p in found if os.path.isdir(p)]
    return shell_sorted(found)


def word_re(word: str) -> re.Pattern:
    """grep -w: not preceded or followed by a letter, digit or underscore."""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])")


def cut_bytes(text: str, n: int) -> str:
    """cut -c1-N, which counts bytes."""
    return text.encode()[:n].decode("utf-8", "ignore")
