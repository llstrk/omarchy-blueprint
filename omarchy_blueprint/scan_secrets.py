"""Look for keys, tokens and passwords in a folder before it is committed.

  bin/check-secrets DIR

Exits 1 when it finds something that is almost certainly a secret, and only
warns about lines that merely look like one. Matches are shown masked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .env import looks_text, split_lines, walk

STRONG = re.compile(
    r"-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"
    r"|tskey-[a-z]+-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-ant-[A-Za-z0-9_-]{20,}"
    r"|sk-[A-Za-z0-9]{32,}|glpat-[A-Za-z0-9_-]{20}|AIza[0-9A-Za-z_-]{35}")
# A key that names a credential, set to a literal value. The value must look
# like a secret (a digit in it, or long), so code such as authUrl = parsed.authUrl
# and settings such as token = "terminal" stay quiet.
WEAK = re.compile(r"""(password|passwd|secret|token|api[_-]?key|auth[_-]?key|credential)[A-Za-z_]*["']?\s*[=:]\s*["']?([^\s"'(){};,]{8,})""", re.I)
COMMENT = re.compile(r"^\s*#")


def mask(line: str) -> str:
    return re.sub(r"([A-Za-z0-9_=+/-]{4})[A-Za-z0-9_=+/-]{6,}", r"\1…", line)


def looks_secret(value: str) -> bool:
    return (any(c.isdigit() for c in value) or len(value) >= 20) and not re.fullmatch(r"[A-Za-z_.]+(\.[A-Za-z_]+)*", value)


def scan(root: str) -> tuple[list[str], list[str]]:
    strong, weak = [], []
    for n in walk(root, prune=lambda n: n.is_dir and n.name == ".git"):
        if not n.is_file:
            continue
        try:
            data = Path(n.path).read_bytes()
        except OSError:
            continue
        if not looks_text(data):
            continue
        for i, line in enumerate(split_lines(data.decode("utf-8")), 1):
            where = f"{n.path}:{i}:{line}"
            if STRONG.search(line):
                strong.append(where)
            elif not COMMENT.match(line) and any(looks_secret(m.group(2)) for m in WEAK.finditer(line)):
                weak.append(where)
    return strong, weak


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: check-secrets DIR", file=sys.stderr)
        return 2
    strong, weak = scan(argv[0])
    if strong:
        print("Secrets found. Remove them before committing:")
        for line in strong:
            print("  " + mask(line)[:200])
    if weak:
        print("Lines that look like credentials. Check each one:")
        for line in weak:
            print("  " + mask(line)[:200])
    if not strong and not weak:
        print(f"No secrets found in {argv[0]}.")
    return 1 if strong else 0
