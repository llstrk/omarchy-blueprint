"""The test VM: QEMU, its control socket, ssh, and the restore driver.

The commands next to this file (run, fresh, restore, stop, ssh, qmp) are
launchers for main() here. Everything that belongs to one machine lives in the
state folder outside this repo (OMARCHY_VM_DIR, default ~/VMs/omarchy-test):
the disk images, the VM's ssh key, local.env with its password, and serve/.
See docs/validation.md.

VM=2 before any command picks a second instance next to the first.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVMF = Path("/usr/share/edk2/x64")
SERVE_PORT = 8765  # the VM reaches it at 10.0.2.2
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# What `mise bootstrap --dry-run` prints for work it would do.
PENDING = re.compile(r"(cp |yay |sudo |pacman |git clone|systemctl)")
HYPR_ENV = ("export XDG_RUNTIME_DIR=/run/user/1000 "
            "HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr | head -1); ")


class Stop(Exception):
    """End the command with this message and exit code."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines, as local.env holds them. Nothing is expanded."""
    env = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.removeprefix("export ").strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            env[key] = value
    return env


@dataclass
class Machine:
    dir: Path
    n: int
    env: dict

    @classmethod
    def here(cls) -> "Machine":
        d = Path(os.environ.get("OMARCHY_VM_DIR") or Path.home() / "VMs/omarchy-test")
        if not d.is_dir():
            raise Stop(f"No VM folder at {d}. See docs/validation.md to set one up.", 2)
        n = os.environ.get("VM", "1")
        if not n.isdigit() or not 1 <= int(n) <= 9:
            raise Stop(f"VM={n}: use a number from 1 to 9.", 2)
        # local.env sets VM_PASSWORD (the test VM's disk and sudo password, a
        # VM-only one) and optionally MIRROR_GITHUB_USER. It is never committed.
        return cls(d, int(n), read_env(d / "local.env"))

    def setting(self, key: str) -> str:
        return os.environ.get(key) or self.env.get(key, "")

    @property
    def sfx(self) -> str:
        return "" if self.n == 1 else str(self.n)

    @property
    def port(self) -> int:  # ssh, on this machine only
        return 2221 + self.n

    @property
    def qmp_sock(self) -> Path:
        return self.dir / f"qmp{self.sfx}.sock"

    @property
    def password(self) -> str:
        pw = self.setting("VM_PASSWORD")
        if not pw:
            raise Stop(f"Set VM_PASSWORD in {self.dir}/local.env (the test VM's own password).", 2)
        return pw

    def ssh_args(self, *command: str) -> list[str]:
        return ["ssh", "-i", str(self.dir / "vm_key"), "-p", str(self.port),
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
                "user@localhost", *command]

    def sh(self, script: str, input: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        """Run a shell command in the VM."""
        return subprocess.run(self.ssh_args(script), input=input, capture_output=True, text=True, timeout=timeout)

    def sh_bytes(self, script: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(self.ssh_args(script), capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)

    def up(self) -> bool:
        try:
            return self.sh("true", timeout=20).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def qmp(self) -> "QMP":
        return QMP(self.qmp_sock)

    def running(self) -> bool:
        if not self.qmp_sock.is_socket():
            return False
        try:
            with self.qmp() as q:
                q.cmd("query-status")
            return True
        except (OSError, ValueError, RuntimeError):
            return False


# QEMU's control socket: screenshots, typing, quitting.

SHIFTED = {'~': 'grave_accent', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8',
           '(': '9', ')': '0', '_': 'minus', '+': 'equal', '{': 'bracket_left', '}': 'bracket_right', '|': 'backslash',
           ':': 'semicolon', '"': 'apostrophe', '<': 'comma', '>': 'dot', '?': 'slash'}
PLAIN = {' ': 'spc', '\n': 'ret', '\t': 'tab', '-': 'minus', '=': 'equal', '[': 'bracket_left', ']': 'bracket_right',
         '\\': 'backslash', ';': 'semicolon', "'": 'apostrophe', ',': 'comma', '.': 'dot', '/': 'slash', '`': 'grave_accent'}


def keys_for(ch: str) -> list[str]:
    if ch.isascii() and ch.isalpha():
        return (["shift"] if ch.isupper() else []) + [ch.lower()]
    if ch.isascii() and ch.isdigit():
        return [ch]
    if ch in PLAIN:
        return [PLAIN[ch]]
    if ch in SHIFTED:
        return ["shift", SHIFTED[ch]]
    raise Stop(f"Cannot type {ch!r} into the VM.", 2)


class QMP:
    def __init__(self, sock: Path, timeout: float = 10):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(timeout)
        self.s.connect(str(sock))
        self.f = self.s.makefile("rw")
        self.f.readline()  # the greeting
        self.cmd("qmp_capabilities")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # The socket stays open while its file object is: close both, or QEMU,
        # which serves one client at a time, never greets the next one.
        self.f.close()
        self.s.close()

    def cmd(self, name: str, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            if not line:
                raise ConnectionError("QEMU closed the control socket")
            r = json.loads(line)
            if "error" in r:
                raise RuntimeError(r["error"]["desc"])
            if "return" in r:
                return r["return"]

    def press(self, names: list[str], hold: float):
        """Press keys as a person would: modifiers down first, then the key, then
        everything up in reverse, with small gaps. send-key presses them all in
        the same instant, which made the desktop see shortcuts instead of text."""
        ev = lambda n, down: {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": n}}}
        for n in names:
            self.cmd("input-send-event", events=[ev(n, True)])
            time.sleep(0.03)
        time.sleep(hold)
        for n in reversed(names):
            self.cmd("input-send-event", events=[ev(n, False)])
            time.sleep(0.03)

    def type(self, text: str):
        keys = [keys_for(ch) for ch in text]  # all of it typeable, before the first key
        for k in keys:
            self.press(k, 0.03)
            time.sleep(0.15)

    def key(self, combo: str):
        self.press(combo.split("-"), 0.12)

    def quit(self):
        try:
            self.cmd("quit")
        except ConnectionError:
            pass  # QEMU may close the socket before it answers


# The restore driver.

@dataclass
class Proc:
    pid: int
    ppid: int
    comm: str
    args: str


def parse_ps(text: str) -> list[Proc]:
    """`ps -eo pid=,ppid=,comm=,args=` output."""
    procs = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            procs.append(Proc(int(parts[0]), int(parts[1]), parts[2], parts[3] if len(parts) > 3 else ""))
    return procs


def questions(procs: list[Proc]) -> list[str]:
    """What waits on a person: a sudo with no child (asking for the password; the
    -n refresh never asks) and gum's questions. Each starts with its pid, so the
    same text asked again is a new question."""
    parents = {p.ppid for p in procs}
    asks = [f"{p.pid} sudo password" for p in procs
            if p.comm == "sudo" and p.pid not in parents and " -n " not in f" {p.args} "]
    asks += [f"{p.pid} {p.args}" for p in procs
             if p.comm == "gum" and re.match(r"gum (confirm|choose|input)\b", p.args)]
    return asks


def finished(procs: list[Proc]) -> str | None:
    """Omarchy's Done screen is up: the exit code it shows ("" if none), else None."""
    for p in procs:
        m = re.match(r"/bin/bash \S*omarchy-show-done\b *(\S*)", p.args)
        if m:
            return m.group(1)
    return None


def left_running(procs: list[Proc], name: str) -> list[Proc]:
    return [p for p in procs if f"/{name}/bootstrap.sh" in p.args or re.match(r"sudo -n -v\b", p.args)]


def short(question: str) -> str:
    """A question as the timeline shows it: without gum's options."""
    text = question.split(" ", 1)[1] if question[:1].isdigit() else question
    text = re.sub(r"(?:^|\s)--[a-z-]+(?:=\S*)?", "", text)
    text = re.sub(r"^\s*gum (?:confirm|choose|input)\s*", "", text)
    return text.strip()[:70]


KEYS = {"y": "y", "n": "n", "enter": "\n", "password": None}


class Answers:
    """Lines of  <regex> TAB y | n | enter | password,  first match wins."""

    def __init__(self, rules: list[tuple[re.Pattern, str]]):
        self.rules = rules

    @classmethod
    def parse(cls, text: str, where: str = "answers") -> "Answers":
        rules = []
        for i, line in enumerate(text.splitlines(), 1):
            if not line.strip() or line.startswith("#"):
                continue
            regex, sep, key = line.partition("\t")
            key = key.strip()
            if not sep or key not in KEYS:
                raise Stop(f"{where}:{i}: want <regex> TAB {' | '.join(KEYS)}, got: {line!r}", 2)
            try:
                rules.append((re.compile(regex), key))
            except re.error as e:
                raise Stop(f"{where}:{i}: {e}", 2) from None
        return cls(rules)

    def find(self, question: str) -> str | None:
        text = question.split(" ", 1)[1] if question[:1].isdigit() else question
        return next((key for regex, key in self.rules if regex.search(text)), None)


class Log:
    """The restore's log in the VM, read a piece at a time: the step headers it
    passes, and the "Left for you" list at the end."""

    def __init__(self, titles: set[str]):
        self.titles = titles
        self.name = ""
        self.offset = 0
        self.partial = b""
        self.later: list[str] | None = None
        self.in_later = False

    def feed(self, name: str, chunk: bytes) -> list[str]:
        """Takes what the log grew by; returns the step titles that went past."""
        if name != self.name:  # a new log
            read_from = self.offset
            self.name, self.offset, self.partial = name, 0, b""
            if read_from:  # the chunk came from the old log's offset: read again
                return []
        self.offset += len(chunk)
        *lines, self.partial = (self.partial + chunk).split(b"\n")
        steps = []
        for raw in lines:
            # script(1) records \r\n; a \r inside a line redraws it.
            for line in ANSI.sub("", raw.decode("utf-8", "replace")).rstrip("\r").split("\r"):
                line = line.rstrip()
                if line in self.titles:
                    steps.append(line)
                elif line.strip().startswith("Left for you"):
                    self.later, self.in_later = [], True
                elif self.in_later:  # the list ends at the first blank line
                    if line.strip():
                        self.later.append(line.strip())
                    else:
                        self.in_later = False
        return steps


def item_name(line: str) -> str:
    """The package or path a plan line (create package:aur:x ...) or a pending
    command (yay -S ... -- x) is about."""
    fields = line.split()
    if fields and fields[0] in ("create", "update") and len(fields) > 1:
        return fields[1].rsplit(":", 1)[-1]
    return fields[-1] if fields else ""


def on_list(line: str, later: list[str]) -> bool:
    name = item_name(line)
    return bool(name) and any(re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", l) for l in later)


def unlisted(lines: list[str], later: list[str]) -> list[str]:
    return [l for l in lines if not on_list(l, later)]


def mark(line: str, later: list[str]) -> str:
    return line.rstrip() + ("   (on the Left for you list)" if on_list(line, later) else "")


def poll_script(offset: int) -> str:
    # The marker is printed in two halves, so ps (which shows this very
    # command) never prints it whole.
    return ("ps -eo pid=,ppid=,comm=,args=; printf '\\n%s%s\\n' '::omarchy-' 'log::'; "
            "f=$(ls -t ~/.local/state/*/restore-*.log 2>/dev/null | head -1); "
            f'[ -n "$f" ] || exit 0; echo "$f"; tail -c +{offset + 1} "$f"')


def split_poll(out: bytes) -> tuple[list[Proc], str, bytes]:
    ps, _, rest = out.partition(b"\n::omarchy-log::\n")
    name, _, chunk = rest.partition(b"\n")
    return parse_ps(ps.decode("utf-8", "replace")), name.decode("utf-8", "replace"), chunk


class Restore:
    POLL = 3  # seconds
    LIMIT = 2 * 3600

    def __init__(self, m: Machine, repo: Path, answers: Answers):
        self.m, self.repo, self.answers = m, repo, answers
        self.name = repo.name
        self.start = time.monotonic()
        titles = re.findall(r'^header "([^"]*)"', "\n".join(f.read_text() for f in repo.glob("steps/*.sh")), re.M)
        self.log = Log(set(titles))

    def stamp(self, text: str):
        s = int(time.monotonic() - self.start)
        print(f"{s // 60:3d}:{s % 60:02d}  {text}", flush=True)

    def answer(self, text: str) -> bool:
        """Type only when the popup has the keyboard and the screen is not locked:
        a person would not have to fix focus first."""
        r = self.m.sh(HYPR_ENV + "hyprctl activewindow -j; echo; pgrep -x hyprlock >/dev/null && echo locked || echo free")
        body, _, lock = r.stdout.strip().rpartition("\n")
        try:
            window = json.loads(body or "{}")
        except ValueError:
            return False
        if window.get("title") != "Omarchy" or window.get("workspace", {}).get("name") != "1" or lock != "free":
            return False
        with self.m.qmp() as q:
            q.type(text)
        return True

    def send_repo(self) -> str:
        """The setup repo goes over as a bundle, cloned where docs/restore.md puts it."""
        git = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True)
        branch = git("symbolic-ref", "--short", "HEAD").stdout.strip()
        if not branch:
            raise Stop(f"{self.repo} is not a git repo on a branch.", 2)
        if git("status", "--porcelain").stdout.strip():
            print(f"Note: {self.repo} has uncommitted changes; the VM gets the last commit.")
        serve_up(self.m)
        bundle = self.m.dir / "serve" / f"{self.name}.bundle"
        r = git("bundle", "create", "-q", str(bundle), branch)
        if r.returncode != 0:
            raise Stop(f"git bundle failed: {r.stderr.strip()}")
        # Private repos come from copies in serve/git, so the VM never needs a
        # GitHub login. The redirect goes in ~/.gitconfig: the restore replaces
        # ~/.config/git/config.
        user = self.m.setting("MIRROR_GITHUB_USER")
        if user and (self.m.dir / "serve/git").is_dir():
            self.m.sh("git config --file ~/.gitconfig "
                      + shlex.quote(f"url.http://10.0.2.2:{SERVE_PORT}/git/.insteadOf")
                      + " " + shlex.quote(f"https://github.com/{user}/"))
        dest, q = f"~/Work/{shlex.quote(self.name)}", shlex.quote
        r = self.m.sh(f"[ -d {dest} ] || {{ curl -sfo /tmp/setup.bundle "
                      f"{q(f'http://10.0.2.2:{SERVE_PORT}/{self.name}.bundle')} && "
                      f"git clone -q -b {q(branch)} /tmp/setup.bundle {dest}; }} && git -C {dest} log --oneline -1")
        if r.returncode != 0:
            raise Stop(f"Could not clone the setup repo in the VM: {(r.stdout + r.stderr).strip()}")
        return r.stdout.strip()

    def poll(self) -> tuple[list[Proc], list[str]] | None:
        try:
            r = self.m.sh_bytes(poll_script(self.log.offset))
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0:
            return None
        procs, name, chunk = split_poll(r.stdout)
        return procs, (self.log.feed(name, chunk) if name else [])

    def run(self) -> int:
        print(f"        repo: {self.send_repo()}")
        # Open a terminal and start the restore there, as a person would.
        with self.m.qmp() as q:
            q.key("meta_l-ret")
        time.sleep(3)
        with self.m.qmp() as q:
            q.type(f"$HOME/Work/{self.name}/bootstrap.sh\n")  # expands in the VM
        self.stamp(f"started ~/Work/{self.name}/bootstrap.sh")

        seen, sudos, asked = None, 0, 0
        while time.monotonic() - self.start < self.LIMIT:
            time.sleep(self.POLL)
            got = self.poll()
            if got is None:
                continue
            procs, steps = got
            for step in steps:
                self.stamp(f"step: {step}")
            code = finished(procs)
            if code is not None:
                self.stamp(f"finished, exit {code or '?'}: {asked} questions, sudo asked {sudos} times")
                self.answer("\n")  # close Omarchy's Done screen
                time.sleep(2)
                ok = self.after()
                if code != "0":
                    return int(code) if code.isdigit() else 1
                return 0 if ok else 4
            asks = questions(procs)
            if not asks:
                seen = None
                continue
            # Answer a question only once it has been there for two polls: a sudo
            # that has just started has no child yet either.
            if asks[0] != seen:
                seen = asks[0]
                continue
            key = self.answers.find(seen)
            if key is None:
                self.stamp(f"UNKNOWN QUESTION, stopping: {seen.split(' ', 1)[1]}")
                return 2
            send = self.m.password + "\n" if key == "password" else KEYS[key]
            if not self.answer(send):
                self.stamp(f"popup lost the keyboard at: {short(seen)}")
                return 3
            sudos += key == "password"
            asked += 1
            self.stamp(f"  answered {key}: {short(seen)}")
            seen = None
            time.sleep(2)
        self.stamp("timed out")
        return 1

    def after(self) -> bool:
        """Checks after the run, as on a machine someone just restored."""
        if self.log.later:
            print("        Left for you:")
            for line in self.log.later:
                print(f"          {line}")
        in_repo = f"cd ~/Work/{shlex.quote(self.name)}; " + HYPR_ENV
        results = []

        def check(label: str, value, good: bool, details=()):
            results.append(good)
            print(f"        {'✓' if good else '✗'} {label}: {value}")
            for d in list(details)[:15]:
                print(f"            {d}")

        plan = self.m.sh(in_repo + "mise bootstrap plan 2>&1", timeout=300).stdout
        lines = ANSI.sub("", plan).splitlines()
        summary = next((l for l in lines if l.startswith("Plan:")), "no plan")
        # Work the restore did not finish is fine when it says so on the list it
        # ends with. What fails is work left undone without a word.
        later = self.log.later or []
        changes = [l for l in lines if re.match(r"(create|update) ", l)]
        check("plan", summary.removeprefix("Plan: "), bool(summary.startswith("Plan:")) and not unlisted(changes, later),
              [mark(l, later) for l in changes])
        dry = ANSI.sub("", self.m.sh(in_repo + "mise bootstrap --dry-run 2>&1", timeout=300).stdout)
        pending = [l for l in dry.splitlines() if PENDING.match(l)]
        check("pending", len(pending), not unlisted(pending, later), [mark(l, later) for l in pending])
        units = self.m.sh("systemctl --failed --no-legend --plain; systemctl --user --failed --no-legend --plain")
        failed = [l.split()[0] for l in units.stdout.splitlines() if l.strip()]
        check("failed units", len(failed), not failed, failed)
        errors = [l for l in self.m.sh(in_repo + "hyprctl configerrors").stdout.splitlines() if l.strip()]
        check("Hyprland config errors", len(errors), not errors, errors)
        procs = parse_ps(self.m.sh("ps -eo pid=,ppid=,comm=,args=").stdout)
        left = left_running(procs, self.name)
        check("left running", len(left), not left, [p.args for p in left])
        return all(results)


def serve_up(m: Machine):
    """The VM fetches setup repos and mirrors from serve/ at 10.0.2.2:8765."""
    serve = m.dir / "serve"
    serve.mkdir(exist_ok=True)
    if port_open(SERVE_PORT):
        return
    with open(m.dir / "http.log", "w") as log:
        subprocess.Popen([sys.executable, "-m", "http.server", str(SERVE_PORT), "--bind", "127.0.0.1"],
                         cwd=serve, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    for _ in range(50):
        if port_open(SERVE_PORT):
            return
        time.sleep(0.1)
    raise Stop(f"Could not serve {serve} on port {SERVE_PORT}: see {m.dir}/http.log")


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


# The commands.

def cmd_run(m: Machine, argv: list[str]) -> int:
    """Start a test VM with QEMU, in the foreground (fresh starts it in the background).

  tests/vm/run install ISO   install Omarchy from ISO onto disk.qcow2 (once)
  tests/vm/run base          boot the installed disk itself: changes stick
  tests/vm/run test          boot a throwaway copy of the installed disk; every
                             test run starts again from the clean install

Headless in test mode unless WINDOW=1. ssh reaches it on 127.0.0.1:2222 (VM=2: 2223)."""
    mode = argv[0] if argv else "test"
    if mode not in ("install", "base", "test"):
        raise Stop("usage: tests/vm/run install ISO | base | test", 2)
    if m.running():
        raise Stop(f"VM {m.n} is already running. Stop it with: VM={m.n} tests/vm/stop")
    d = m.dir
    disk, vars_ = d / "disk.qcow2", d / "OVMF_VARS.fd"
    extra = []
    if mode == "install":
        if len(argv) < 2 or not Path(argv[1]).is_file():
            raise Stop("usage: tests/vm/run install OMARCHY.iso", 2)
        extra = ["-cdrom", str(Path(argv[1]).resolve()), "-boot", "once=d"]
        if not disk.exists():
            subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", str(disk), "40G"], check=True)
    if not disk.exists():
        raise Stop(f"No clean install at {disk}: run tests/vm/run install ISO first.", 2)
    if not vars_.exists():
        shutil.copy(OVMF / "OVMF_VARS.4m.fd", vars_)
    if mode == "test":
        disk2, vars2 = d / f"test{m.sfx}.qcow2", d / f"test{m.sfx}_VARS.fd"
        disk2.unlink(missing_ok=True)
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-b", disk.name, "-F", "qcow2", str(disk2)],
                       check=True, cwd=d)
        shutil.copy(vars_, vars2)
        disk, vars_ = disk2, vars2
    window = os.environ.get("WINDOW") == "1" or mode != "test"
    m.qmp_sock.unlink(missing_ok=True)
    qemu = ["qemu-system-x86_64", "-name", f"omarchy-test ({mode}{m.sfx})", "-enable-kvm", "-machine", "q35",
            "-cpu", "host", "-smp", "4", "-m", "8G",
            "-drive", f"if=pflash,format=raw,readonly=on,file={OVMF / 'OVMF_CODE.4m.fd'}",
            "-drive", f"if=pflash,format=raw,file={vars_}",
            "-drive", f"file={disk},if=virtio,format=qcow2", *extra,
            "-device", "virtio-vga", "-display", "gtk,gl=off,zoom-to-fit=on" if window else "none",
            "-device", "virtio-keyboard", "-device", "virtio-tablet",
            "-nic", f"user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{m.port}-:22",
            "-audiodev", "pipewire,id=snd", "-device", "intel-hda", "-device", "hda-duplex,audiodev=snd",
            "-qmp", f"unix:{m.qmp_sock},server=on,wait=off"]
    os.execvp(qemu[0], qemu)


def cmd_fresh(m: Machine, argv: list[str]) -> int:
    """Boot a blank test VM (a throwaway copy of the clean install), unlock its disk
and wait until ssh answers. The clean install itself is never changed.

  tests/vm/fresh            VM=2 tests/vm/fresh for a second instance

It will not replace a VM that is already running: that may be someone's
session. Stop it first with: tests/vm/stop"""
    password = m.password
    if m.running():
        raise Stop(f"VM {m.n} is already running. Stop it with: VM={m.n} tests/vm/stop")
    log = m.dir / f"qemu{m.sfx}.log"
    with open(log, "w") as out:
        qemu = subprocess.Popen([str(HERE / "run"), "test"], stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        if m.running() or qemu.poll() is not None:
            break
        time.sleep(1)
    if not m.running():
        raise Stop(f"QEMU did not start: see {log}")
    time.sleep(20)  # firmware and bootloader, up to the disk password
    with m.qmp() as q:
        q.type(password + "\n")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if m.up():
            print(f"VM {m.n} is up (ssh port {m.port})")
            return 0
        time.sleep(3)
    raise Stop(f"VM {m.n} did not answer on ssh. A look at the screen: VM={m.n} tests/vm/qmp shot screen.png")


def cmd_restore(m: Machine, argv: list[str]) -> int:
    """Run a whole restore in a blank test VM through the real popup, answering the
way a person would, and print a timeline: when each step started, every
answer, how often sudo asked for the password, and checks afterwards.

  tests/vm/fresh && tests/vm/restore SETUP_REPO [ANSWERS]

SETUP_REPO is a generated setup repo (a git repo: its current branch is what
the VM gets). ANSWERS defaults to answers.default next to this script. Each of
its lines is  <regex matched against the question> TAB y | n | enter | password.
An unknown question stops the run and leaves the VM as it is.

Exits with bootstrap.sh's exit code, or 2 (unknown question), 3 (the popup
lost the keyboard), 4 (a check afterwards failed) or 1 (timed out)."""
    if not 1 <= len(argv) <= 2:
        raise Stop("usage: tests/vm/restore SETUP_REPO [ANSWERS]", 2)
    repo = Path(argv[0]).resolve()
    path = Path(argv[1]) if len(argv) > 1 else HERE / "answers.default"
    answers = Answers.parse(path.read_text(), str(path))
    m.password  # noqa: B018 (stops early when it is not set)
    if not m.running() or not m.up():
        raise Stop(f"VM {m.n} is not up: run tests/vm/fresh first.")
    return Restore(m, repo, answers).run()


def cmd_stop(m: Machine, argv: list[str]) -> int:
    """Stop a test VM at once. Its disk is a throwaway copy, so nothing is lost.

  tests/vm/stop             VM=2 tests/vm/stop for the second instance"""
    if not m.running():
        print(f"VM {m.n} is not running.")
        return 0
    with m.qmp() as q:
        q.quit()
    print(f"VM {m.n} stopped.")
    return 0


def cmd_ssh(m: Machine, argv: list[str]) -> int:
    """A shell in the test VM, or one command:  tests/vm/ssh ['command']   (VM=2 for the second)"""
    os.execvp("ssh", m.ssh_args(*argv))


def cmd_qmp(m: Machine, argv: list[str]) -> int:
    """Drive a test VM through QEMU's control socket.

  tests/vm/qmp shot FILE.png       screenshot of the VM's screen
  tests/vm/qmp type 'TEXT'         type text (\\n is Enter)
  tests/vm/qmp key ctrl-alt-t      press a key combination (qcode names joined by -)
  tests/vm/qmp powerdown           ask the guest to shut down (ACPI; Omarchy opens its menu)
  tests/vm/qmp quit                stop the VM at once (test disks are thrown away anyway)
  tests/vm/qmp status              is the VM running"""
    if not argv or (argv[0] in ("shot", "type", "key") and len(argv) != 2):
        raise Stop(cmd_qmp.__doc__, 2)
    if not m.running():
        raise Stop(f"VM {m.n} is not running.")
    with m.qmp() as q:
        match argv[0]:
            case "shot":
                q.cmd("screendump", filename=str(Path(argv[1]).resolve()), format="png")
            case "type":
                q.type(argv[1].encode().decode("unicode_escape"))
            case "key":
                q.key(argv[1])
            case "powerdown":
                q.cmd("system_powerdown")
            case "quit":
                q.quit()
            case "status":
                print(q.cmd("query-status")["status"])
            case _:
                raise Stop(cmd_qmp.__doc__, 2)
    return 0


COMMANDS = {"run": cmd_run, "fresh": cmd_fresh, "restore": cmd_restore, "stop": cmd_stop,
            "ssh": cmd_ssh, "qmp": cmd_qmp}


def main(command: str, argv: list[str]) -> int:
    fn = COMMANDS[command]
    if argv[:1] in (["-h"], ["--help"]):
        print(fn.__doc__)
        return 0
    try:
        return fn(Machine.here(), argv)
    except Stop as e:
        print(e, file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return 130
