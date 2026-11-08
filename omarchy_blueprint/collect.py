"""Run every collector and write inventory.json. Read-only: nothing on the machine changes.

  bin/inspect [--out DIR] [--offline] [--only NAME]

  --out DIR    where to write inventory.json (default: out/ in this repo)
  --offline    do not check whether repo remotes can be reached
  --only NAME  run one collector and print its items (for working on its rules)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import SCHEMA
from .collectors import commands, configs, hardware, identity, packages, plugins, repos, services, system, tools
from .env import Env, shell_sorted

KIT = Path(__file__).resolve().parent.parent

# Shown in this order. When two collectors report the same id, the first in
# DEDUP_ORDER wins (alphabetical, as the item files were once concatenated).
COLLECTORS = {
    "packages": packages, "configs": configs, "system": system, "services": services, "repos": repos,
    "plugins": plugins, "commands": commands, "tools": tools, "identity": identity,
}
DEDUP_ORDER = sorted(COLLECTORS)


def module_slug(vendor: str) -> str:
    """The hardware module's default name: the vendor (framework), not "machine"."""
    slug = re.sub(r"[^a-z0-9]+", "-", vendor.lower()).removeprefix("-").removesuffix("-")
    return slug or "machine"


def run_collectors(env: Env, names) -> dict[str, tuple[list[dict], float, str]]:
    def one(name):
        start = time.monotonic()
        try:
            found, error = COLLECTORS[name].collect(env), ""
        except Exception as e:  # report and carry on: one broken rule should not hide the rest
            found, error = [], f"{type(e).__name__}: {e}"
            traceback.print_exc(file=sys.stderr)
        return name, (found, time.monotonic() - start, error)

    with ThreadPoolExecutor(len(names)) as pool:
        return dict(pool.map(one, names))


def build(env: Env, results: dict, machine: dict) -> dict:
    mod = module_slug(machine.get("vendor", ""))
    seen, items = set(), []
    for name in DEDUP_ORDER:
        for it in results.get(name, ([], 0, ""))[0]:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            if it["module"] == "machine":
                it = {**it, "module": mod}
            items.append(it)
    items.sort(key=lambda it: (it["kind"], it["name"]))
    counts: dict[str, int] = {}
    for it in items:
        counts[it["class"]] = counts.get(it["class"], 0) + 1

    dots = ""
    m = re.search(r"(https://|git@|ssh://|file://)[^ \n]+", env.run("mise", "dot", "origin").out)
    if m:
        dots = m.group(0)
    omarchy_version = env.run("pacman", "-Q", "omarchy").out.split()
    mise_version = env.run("mise", "--version").out.split()
    return {
        "schema": SCHEMA,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "omarchy": {"version": omarchy_version[1] if len(omarchy_version) > 1 else "", "path": str(env.omarchy)},
        "mise": mise_version[0] if mise_version else "",
        "user": env.user, "home": str(env.home), "dots_origin": dots, "machine": machine,
        "counts": dict(sorted(counts.items())),
        "items": items,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bin/inspect", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(KIT / "out"))
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", choices=sorted(COLLECTORS))
    args = ap.parse_args(argv)

    env = Env.from_system(offline=args.offline)
    if not env.omarchy.is_dir():
        print(f"Omarchy not found (looked in {env.omarchy}).", file=sys.stderr)
        return 1
    for cmd in ("git", "pacman", "systemctl"):
        if not env.which(cmd):
            print(f"{cmd} is required.", file=sys.stderr)
            return 1
    env.corpus  # read Omarchy's files once, before the collectors share it
    shell_sorted([])  # set the collation locale here, not inside a collector thread

    if args.only:
        found, _, error = run_collectors(env, [args.only])[args.only]
        for it in found:
            print(json.dumps(it, ensure_ascii=False))
        return 1 if error else 0

    print("Inspecting this machine (read-only)...", file=sys.stderr)
    with ThreadPoolExecutor(1) as pool:
        machine_future = pool.submit(hardware.collect, env)
        results = run_collectors(env, list(COLLECTORS))
        try:
            machine = machine_future.result()
        except Exception:
            machine = {}
    for name in COLLECTORS:
        found, secs, error = results[name]
        line = f"  {name:<9} {len(found):>3} items  {secs:.0f}s"
        print(line + (f"  ({error})" if error else ""), file=sys.stderr)

    inventory = build(env, results, machine)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n")
    counts = ", ".join(f"{v} {k}" for k, v in inventory["counts"].items())
    print(f"\nFound: {counts}\nWrote {out / 'inventory.json'}", file=sys.stderr)
    return 0
