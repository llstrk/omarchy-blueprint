"""Facts about this machine, as one object (not items). The agent uses them to
name hardware modules and write their detect scripts."""

from __future__ import annotations

import json
import re

from ..env import Env, read_text


def collect(env: Env) -> dict:
    def dmi(key: str) -> str:
        return re.sub(r" *$", "", re.sub(r" +", " ", read_text(env.dmi / key).rstrip("\n")))

    cpuinfo = read_text(env.cpuinfo)
    cpu = "unknown"
    if "GenuineIntel" in cpuinfo:
        cpu = "intel"
    if "AuthenticAMD" in cpuinfo:
        cpu = "amd"
    if env.machine_arch == "aarch64":
        cpu = "arm"
    m = re.search(r"^model name\s*: (.*)$", cpuinfo, re.M)

    gpus = [re.sub(r"^[^ ]* ", "", line) for line in env.run("lspci").lines() if re.search(r"vga|3d|display", line, re.I)]
    try:
        monitors = [{k: mon.get(k) for k in ("name", "description", "width", "height", "refreshRate", "scale")}
                    for mon in json.loads(env.run("hyprctl", "monitors", "-j").out)]
    except (ValueError, TypeError, AttributeError):
        monitors = []

    def yes(cmd: str) -> bool:
        return env.run(cmd).ok

    return {
        "vendor": dmi("sys_vendor"), "product": dmi("product_name"), "family": dmi("product_family"),
        "version": dmi("product_version"), "board": dmi("board_name"), "chassis_type": dmi("chassis_type"),
        "cpu": cpu, "cpu_model": m.group(1) if m else "", "gpus": gpus,
        "laptop": yes("omarchy-hw-laptop"), "fingerprint_reader": yes("omarchy-hw-fingerprint"),
        "touchscreen": yes("omarchy-hw-touchscreen"), "monitors": monitors,
        "hostname": read_text(env.etc / "hostname").rstrip("\n"), "kernel": env.kernel,
    }
