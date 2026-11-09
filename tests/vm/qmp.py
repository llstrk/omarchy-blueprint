#!/usr/bin/env python3
"""Drive a test VM through QEMU's control socket ($QMP_SOCK): screenshots and typing.

  qmp.py shot FILE.png       screenshot of the VM's screen
  qmp.py type 'TEXT'         type text (\\n is Enter)
  qmp.py key ctrl-alt-t      press a key combination (qcode names joined by -)
  qmp.py powerdown           ask the guest to shut down (ACPI)
  qmp.py quit                stop the VM at once (test disks are thrown away anyway)
  qmp.py status              is the VM running

The scripts next to this one set QMP_SOCK (lib.sh).
"""
import json
import os
import socket
import sys
import time
from pathlib import Path

SOCK = Path(os.environ["QMP_SOCK"])

SHIFTED = {'~': 'grave_accent', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8',
           '(': '9', ')': '0', '_': 'minus', '+': 'equal', '{': 'bracket_left', '}': 'bracket_right', '|': 'backslash',
           ':': 'semicolon', '"': 'apostrophe', '<': 'comma', '>': 'dot', '?': 'slash'}
PLAIN = {' ': 'spc', '\n': 'ret', '\t': 'tab', '-': 'minus', '=': 'equal', '[': 'bracket_left', ']': 'bracket_right',
         '\\': 'backslash', ';': 'semicolon', "'": 'apostrophe', ',': 'comma', '.': 'dot', '/': 'slash', '`': 'grave_accent'}

class QMP:
    def __init__(self):
        self.s = socket.socket(socket.AF_UNIX); self.s.connect(str(SOCK)); self.f = self.s.makefile("rw")
        self.f.readline(); self.cmd("qmp_capabilities")
    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n"); self.f.flush()
        while True:
            r = json.loads(self.f.readline())
            if "return" in r or "error" in r:
                if "error" in r: raise SystemExit(r["error"]["desc"])
                return r["return"]

def keys_for(ch):
    if ch.isalpha(): return (["shift"] if ch.isupper() else []) + [ch.lower()]
    if ch.isdigit(): return [ch]
    if ch in PLAIN: return [PLAIN[ch]]
    if ch in SHIFTED: return ["shift", SHIFTED[ch]]
    raise SystemExit(f"cannot type {ch!r}")

def press(q, names, hold=60):
    """Press keys as a person would: modifiers down first, then the key, then
    everything up in reverse, with small gaps. send-key presses them all in the
    same instant, which made the desktop see shortcuts instead of text."""
    ev = lambda n, down: {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": n}}}
    for n in names:
        q.cmd("input-send-event", events=[ev(n, True)]); time.sleep(0.03)
    time.sleep(hold / 1000)
    for n in reversed(names):
        q.cmd("input-send-event", events=[ev(n, False)]); time.sleep(0.03)

def main(argv):
    q = QMP()
    if argv[0] == "shot":
        q.cmd("screendump", filename=str(Path(argv[1]).resolve()), format="png")
    elif argv[0] == "type":
        for ch in argv[1].encode().decode("unicode_escape"):
            press(q, keys_for(ch), 30); time.sleep(0.15)
    elif argv[0] == "key":
        press(q, argv[1].split("-"), 120)
    elif argv[0] == "powerdown":
        q.cmd("system_powerdown")
    elif argv[0] == "quit":
        q.cmd("quit")
    elif argv[0] == "status":
        print(q.cmd("query-status")["status"])

main(sys.argv[1:])
