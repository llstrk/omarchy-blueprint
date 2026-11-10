"""The kit's own checks, run on this machine before every push (the pre-push
hook in .githooks runs bin/check). Exits 0 only when every check passes.

  bin/check            everything below
  bin/check --quick    skip generating a repo from out/

With out/inventory.json and out/decisions.json present (bin/inspect, then the
page), it also generates a setup repo from them and checks it is a no-op on
this machine, as AGENTS.md phase 7 does. The restore itself is tested in a VM:
see docs/validation.md.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .scan_secrets import mask, scan

KIT = Path(__file__).resolve().parent.parent
SHELLCHECK = ["mise", "x", "shellcheck@0.11.0", "--", "shellcheck"]
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
EM_DASH = chr(0x2014)  # written as a number so this file passes its own check
# What `mise bootstrap --dry-run` prints for work it would do.
PENDING = re.compile(r"(cp |yay |sudo |pacman |git clone|systemctl)")
# What `bootstrap.sh --check` prints for something it would offer or change.
OFFER = re.compile(r"^  [•!] |✗", re.M)


class Failed(Exception):
    """A check found a problem. The message says what."""


def run(cmd, cwd=KIT, env=None, timeout=600) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def output(p: subprocess.CompletedProcess) -> str:
    return (p.stdout + p.stderr).strip()


def must(p: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    if p.returncode != 0:
        raise Failed(f"exit {p.returncode}\n{output(p)}")
    return p


class Runner:
    def __init__(self):
        self.failed: list[str] = []

    def check(self, name: str, fn, *args) -> bool:
        """Run one check and print a line for it. A check returns a note, or a
        note and lines to show under it, or raises Failed."""
        print(f"  {name:<44}", end="", flush=True)
        try:
            result = fn(*args)
        except Failed as e:
            detail = str(e)
        except subprocess.TimeoutExpired as e:
            detail = f"timed out after {e.timeout} s: {' '.join(map(str, e.cmd))}"
        except FileNotFoundError as e:
            detail = f"not installed: {e.filename}"
        else:
            note, lines = result if isinstance(result, tuple) else (result, [])
            print("ok" + (f"  ({note})" if note else ""))
            for line in lines:
                print("      " + line)
            return True
        print("FAILED")
        for line in detail.splitlines()[-25:]:
            print("      " + line)
        self.failed.append(name)
        return False


def kit_files() -> list[Path]:
    """What git would commit: tracked files and new ones it does not ignore (not out/)."""
    p = must(run(["git", "ls-files", "-z", "-co", "--exclude-standard"]))
    return [Path(f) for f in sorted(set(p.stdout.split("\0"))) if f and (KIT / f).is_file()]


def first_line(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            return f.readline(200).decode("utf-8", "replace")
    except OSError:
        return ""


def unit_tests():
    p = must(run([sys.executable, "-m", "unittest", "discover", "-q", "tests"]))
    m = re.search(r"^Ran (\d+) tests?", output(p), re.M)
    return f"{m.group(1)} tests" if m else None


def python_compiles():
    files = [f for f in kit_files() if f.suffix == ".py" or "python" in first_line(KIT / f)]
    errors = []
    for f in files:
        try:
            compile((KIT / f).read_text(), str(f), "exec")
        except SyntaxError as e:
            errors.append(f"{f}:{e.lineno}: {e.msg}")
    if errors:
        raise Failed("\n".join(errors))
    return f"{len(files)} files"


def shell_scripts():
    # The template is what every setup repo is made of: every level of note.
    # SC1091: it sources lib/ui.sh by a path only a generated repo has.
    template = sorted(KIT.glob("template/bootstrap.sh")) + sorted(KIT.glob("template/lib/*.sh")) + \
        sorted(KIT.glob("template/recipes/*.sh"))
    must(run([*SHELLCHECK, "-x", "-e", "SC1091", *template]))
    # The kit's own bash scripts, found by their first line: warnings and errors.
    own = [f for f in kit_files() if not str(f).startswith("template/") and
           re.match(r"#!.*\bbash\b", first_line(KIT / f))]
    if own:
        must(run([*SHELLCHECK, "-x", "-S", "warning", *own]))
    return f"{len(template) + len(own)} scripts"


def page_script(tmp: Path):
    if not shutil.which("node"):
        return "skipped: node is not installed"
    html = (KIT / "blueprint/index.html").read_text()
    code = re.findall(r'<script(?![^>]*type="application/json")[^>]*>(.*?)</script>', html, re.S)
    js = tmp / "page.js"
    js.write_text("\n".join(code))
    must(run(["node", "--check", js]))


def em_dashes(files: list[Path]) -> list[str]:
    found = []
    for f in files:
        if f.suffix == ".json":
            continue
        try:
            text = (KIT / f).read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found += [f"{f}:{i}: {line.strip()}" for i, line in enumerate(text.splitlines(), 1) if EM_DASH in line]
    return found


def no_em_dashes():
    found = em_dashes(kit_files())
    if found:
        raise Failed("\n".join(found))


def secrets(root: Path):
    """Strong matches fail. Weak ones only warn, and are shown so someone reads them."""
    strong, weak = scan(str(root))
    def show(lines):
        out = []
        for line in lines:
            path, n, text = line.removeprefix(f"{root}/").split(":", 2)
            out.append(f"{path}:{n}: {mask(text.strip())}"[:200])
        return out
    if strong:
        raise Failed("Secrets found. Remove them before committing:\n" + "\n".join(show(strong)))
    return (f"{len(weak)} lines to read" if weak else None), show(weak)


def kit_secrets(tmp: Path):
    copy = tmp / "kit"
    for f in kit_files():
        (copy / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(KIT / f, copy / f)
    return secrets(copy)


class Generated:
    """A setup repo generated from out/, checked on the machine it came from."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.env = dict(os.environ, MISE_TRUSTED_CONFIG_PATHS=f"{repo}:{Path.home()}/.config/mise")
        self.modules = ""

    def sh(self, *cmd, timeout=600):
        return run(cmd, cwd=self.repo, env=self.env, timeout=timeout)

    def generates(self):
        must(run([KIT / "bin/generate", "--allow-undecided", self.repo]))
        # The modules this machine matches, as the modules step would pick them.
        self.modules = ",".join(d.parent.name for d in sorted(self.repo.glob("modules/*/detect"))
                                if os.access(d, os.X_OK) and self.sh(d, timeout=60).returncode == 0)
        self.env["MISE_ENV"] = self.modules

    def plan_is_empty(self):
        plan = output(self.sh("mise", "bootstrap", "plan"))
        summary = next((line for line in plan.splitlines() if line.startswith("Plan:")), "")
        if not summary.startswith("Plan: 0 create, 0 update,"):
            changes = [line for line in plan.splitlines() if re.match(r"(create|update) ", line)]
            raise Failed("\n".join([summary or plan, *changes,
                                    "A file changed since bin/inspect? Run it again (and keep your decisions)."]))
        return f"modules: {self.modules}" if self.modules else None

    def dry_run_is_empty(self):
        lines = pending_in(output(self.sh("mise", "bootstrap", "--dry-run")))
        if lines:
            raise Failed("\n".join(lines))

    def check_offers_nothing(self):
        p = self.sh("./bootstrap.sh", "--check", "--no-popup")
        offers = offers_in(output(p))
        if p.returncode != 0 or offers:
            raise Failed("\n".join([f"exit {p.returncode}", *offers]))

    def shellcheck(self):
        files = [*self.repo.glob("bootstrap.sh"), *sorted(self.repo.glob("lib/*.sh")),
                 *sorted(self.repo.glob("steps/*.sh")), *sorted(self.repo.glob("modules/*/detect"))]
        must(self.sh(*SHELLCHECK, "-x", *[f.relative_to(self.repo) for f in files]))


def pending_in(text: str) -> list[str]:
    return [line for line in ANSI.sub("", text).splitlines() if PENDING.match(line)]


def offers_in(text: str) -> list[str]:
    return [line for line in ANSI.sub("", text).splitlines() if OFFER.search(line)]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv != ["--quick"]:
        print(__doc__.strip())
        return 0 if argv[0] in ("-h", "--help") else 2
    quick = argv == ["--quick"]
    r = Runner()
    with tempfile.TemporaryDirectory(prefix="bin-check.") as t:
        tmp = Path(t)
        print("The kit")
        r.check("unit tests", unit_tests)
        r.check("python compiles", python_compiles)
        r.check("shellcheck", shell_scripts)
        r.check("page script parses", page_script, tmp)
        r.check("no em dashes", no_em_dashes)
        r.check("no secrets", kit_secrets, tmp)
        print()
        if quick:
            print("Skipped generating from out/ (--quick).")
        elif not (KIT / "out/inventory.json").is_file() or not (KIT / "out/decisions.json").is_file():
            print("Skipped generating from out/: run bin/inspect and the page (bin/blueprint) first.")
        else:
            print("A setup repo generated from out/, on this machine")
            g = Generated(tmp / "setup")
            if r.check("generates", g.generates):
                r.check("plan is empty", g.plan_is_empty)
                r.check("dry run has nothing but the task", g.dry_run_is_empty)
                r.check("bootstrap.sh --check offers nothing", g.check_offers_nothing)
                r.check("shellcheck on it", g.shellcheck)
                r.check("no secrets in it", secrets, g.repo)
    print()
    if r.failed:
        print("FAILED: " + ", ".join(r.failed))
        return 1
    print("All checks passed.")
    return 0
