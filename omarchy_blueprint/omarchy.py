"""What Omarchy itself writes, installs and enables, read from its own files.

The corpus is the text of everything Omarchy ships that could install, write or
enable something: install scripts, commands, migrations, defaults, configs and
desktop entries. A path, unit or package named there is Omarchy's, not the
user's.
"""

from __future__ import annotations

import bisect
import re
from pathlib import Path

from .env import Env, files_under, looks_text, size_under, split_lines, word_re

CORPUS_DIRS = ("install", "bin", "migrations", "default", "config", "etc-overrides", "applications")


class Corpus:
    def __init__(self, env: Env):
        parts = []
        for d in CORPUS_DIRS:
            # follow=True: Omarchy's bin/ holds symlinks to its commands in /usr/bin.
            for node in files_under(env.omarchy / d, follow=True):
                if not size_under(node.path, 512):
                    continue
                try:
                    data = Path(node.path).read_bytes()
                except OSError:
                    continue
                if looks_text(data):
                    parts.append(data.decode("utf-8"))
        self.text = "".join(parts)
        self.lines = split_lines(self.text)
        self._starts = [0]
        for line in self.lines:
            self._starts.append(self._starts[-1] + len(line) + 1)

    def mentions(self, s: str) -> bool:
        """Omarchy's files contain s anywhere."""
        return s in self.text

    def mentions_word(self, word: str) -> bool:
        """The same, as a whole word (unit and package names)."""
        return bool(word_re(word).search(self.text))

    def writes_command(self, name: str) -> bool:
        """Omarchy names this command near ~/.local/bin, so one of its installers puts it there.

        A bare word match is not enough: a script called "contacts" would match
        contacts.google.com.
        """
        if "local/bin/" + name in self.text:
            return True
        for m in word_re(name).finditer(self.text):
            i = bisect.bisect_right(self._starts, m.start()) - 1
            if any("local/bin" in near for near in self.lines[max(0, i - 6):i + 7]):
                return True
        return False


def package_list(path: Path) -> list[str]:
    """Package names in an Omarchy .packages file: first word of each line, no comments."""
    names = []
    try:
        text = path.read_text("utf-8", "replace")
    except OSError:
        return names
    for line in split_lines(text):
        if re.match(r"^\s*#", line):
            continue
        words = line.split()
        if words:
            names.append(words[0])
    return names


PKG_ADD = re.compile(r"omarchy-pkg-(aur-)?add( +[A-Za-z0-9@._+-]+)+")


PACMAN_S = re.compile(r"(?:pacman +-S\b|omarchy-pkg-missing\b)[^|;&#)]*")
PKG_NAME = re.compile(r"^[a-z][a-z0-9@._+-]*$")


def installs(text: str) -> set[str]:
    """Package names a script installs: omarchy-pkg-add, plain pacman -S, and the
    omarchy-pkg-missing check in front of it."""
    names = pkg_args(text)
    for line in split_lines(text):
        for m in PACMAN_S.finditer(line):
            words = m.group(0).split()[1:]
            if "--" in words:
                words = words[words.index("--") + 1:]
            # Options and their values (--ask 4) never look like a package name.
            names.update(w for w in words if not w.startswith("-") and PKG_NAME.match(w))
    return names


def pkg_args(text: str) -> set[str]:
    """Package names after omarchy-pkg-add and omarchy-pkg-aur-add."""
    names = set()
    for line in split_lines(text):
        for m in PKG_ADD.finditer(line):
            words = re.sub(r"omarchy-pkg-(aur-)?add", "", m.group(0)).split(" ")
            names.update(w for w in words if re.match(r"^[a-z0-9]", w))
    return names
