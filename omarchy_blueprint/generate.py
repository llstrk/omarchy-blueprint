"""Build a setup repo from the inventory and your decisions.

  bin/generate [options] TARGET

  --out DIR            where inventory.json and decisions.json are (default: out/)
  --decisions FILE     decisions to apply (default: DIR/decisions.json, if present)
  --allow-undecided    leave out items still marked "decide" instead of stopping
  --force              write into TARGET even if it is not empty

TARGET gets mise.toml, one mise.<module>.toml per hardware module, copies of
every carried file, bootstrap.sh with its steps, and a README. Nothing outside
TARGET changes. Files only root can read are listed at the end with the
command to copy them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from . import scan_secrets

KIT = Path(__file__).resolve().parent.parent
TEMPLATE = KIT / "template"

DOTFILE_KINDS = ("config", "desktop-entry", "config-dir", "identity")
STEP_IDS = ("identity:github", "identity:ssh-keys", "identity:tailscale", "identity:fingerprint")


# Quoting -------------------------------------------------------------------

def q(s) -> str:
    """A TOML basic string. JSON strings are valid TOML basic strings."""
    return json.dumps(s, ensure_ascii=False)


def shell_word(s: str) -> str:
    """Quote for a shell the way printf %q does: backslashes, no quotes."""
    if s == "":
        return "''"
    out = []
    for i, ch in enumerate(s):
        if ch in " \t\n'\"\\|&;()<>!{}*[?]^$`" or (i == 0 and ch in "~#"):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def shell_quote(s: str) -> str:
    """Single-quoted, as jq's @sh writes it."""
    return "'" + s.replace("'", "'\\''") + "'"


GITHUB_SSH = re.compile(r"^(?:ssh://)?git@github\.com[:/](.+?)(?:\.git)?/?$")


def clone_url(url: str) -> str:
    """The address a new machine clones from. GitHub over SSH needs a key the new
    machine does not have yet; over HTTPS the GitHub sign-in covers private
    repos. A password in an address is never written down."""
    if m := GITHUB_SSH.match(url):
        return f"https://github.com/{m.group(1)}.git"
    return re.sub(r"^(https?://)[^/@]+@", r"\1", url)


def needs_login(url: str) -> bool:
    """Whether cloning needs more than the GitHub sign-in: SSH to another host, or
    an address that had a password in it. mise stops the restore on a failed clone."""
    clean = clone_url(url)
    return bool(re.match(r"^(ssh://|[^/:@]+@[^/:]+:)", clean)) or (clean != url and "github.com" not in clean)


def get(d: dict, key: str, default):
    """jq's //: missing, null and false all fall back."""
    v = d.get(key)
    return default if v is None or v is False else v


# What lands where ----------------------------------------------------------

class Build:
    def __init__(self, inventory: dict, home: str, today: str):
        self.inv = inventory
        self.items = inventory["items"]
        self.home = home
        self.today = today

    def mine(self, mod: str) -> list[dict]:
        if mod == "":
            return [it for it in self.items if it["class"] == "carry"]
        return [it for it in self.items if it["class"] == "module" and it["module"] == mod]

    @staticmethod
    def root(mod: str) -> str:
        return "" if mod == "" else f"modules/{mod}/"

    def src_home(self, it: dict, mod: str) -> str:
        return self.root(mod) + "home/" + re.sub(r"^~/", "", get(it["facts"], "path", it["name"]))

    def src_etc(self, it: dict, mod: str) -> str:
        return self.root(mod) + "etc/" + re.sub(r"^/etc/", "", get(it["facts"], "path", it["name"]))

    @staticmethod
    def as_home(p: str) -> str:
        return re.sub(r"^~/", "$HOME/", p)

    def abs(self, p: str) -> str:
        return re.sub(r"^~/", self.home + "/", p)

    @staticmethod
    def is_dotfile(it: dict) -> bool:
        f = it["facts"]
        return ((it["kind"] in DOTFILE_KINDS and get(f, "path", "") != "" and (it["kind"] != "identity" or it["name"] == "ssh-config"))
                or (it["kind"] == "plugin" and f.get("deploy") == "copy"))

    @staticmethod
    def is_git(it: dict) -> bool:
        return it["kind"] == "repo" or (it["kind"] in ("plugin", "theme") and it["facts"].get("deploy") == "git")

    @staticmethod
    def reachable(it: dict) -> bool:
        return it["facts"].get("reachable") is not False

    # [bootstrap.*] and [dotfiles] -------------------------------------------

    def packages(self, items):
        return [f'{q(("aur:" if it["facts"].get("source") == "aur" else "pacman:") + it["name"])} = "latest"'
                for it in items if it["kind"] == "package"]

    def files(self, items, mod):
        out = []
        for it in items:
            f = it["facts"]
            if it["kind"] == "system-file":
                out.append(f'[bootstrap.files.{q(it["name"])}]\nsource = {q("./" + self.src_etc(it, mod))}\n'
                           f'owner = {q(get(f, "owner", "root"))}\ngroup = {q(get(f, "group", "root"))}\n'
                           f'mode = {q("0" + get(f, "mode", "644"))}')
            elif it["kind"] in ("user-unit", "command"):
                default = "755" if it["kind"] == "command" else "644"
                out.append(f'[bootstrap.files.{q(get(f, "path", it["name"]))}]\nsource = {q("./" + self.src_home(it, mod))}\n'
                           f'mode = {q("0" + get(f, "mode", default))}')
        return out

    def services(self, items):
        out = []
        for it in items:
            if it["kind"] == "masked-unit":
                out.append(f'[bootstrap.services.{q(it["name"])}]\nstate = "stopped"\nenabled = false\nmasked = true')
            elif it["kind"] == "service":
                f = it["facts"]
                key = re.sub(r"\.service$", "", get(f, "unit", it["name"]))
                state = "stopped" if re.search("oneshot", it["reason"]) else "running"
                out.append(f"[bootstrap.services.{q(key)}]" + ('\nscope = "user"' if f.get("scope") == "user" else "")
                           + f"\nstate = {q(state)}\nenabled = true")
        return out

    def repos(self, items):
        """Repos and git plugins a new machine can clone. Ones that could not be
        reached, or need a login of their own, are cloned in the task instead,
        where a failure does not stop the run."""
        return [f'{q(it["facts"]["path"])} = {{ url = {q(clone_url(it["facts"]["url"]))} }}' for it in items
                if self.is_git(it) and self.reachable(it) and get(it["facts"], "url", "") != ""
                and not needs_login(it["facts"]["url"])]

    def dotfiles(self, items, mod):
        out = []
        for it in items:
            if not self.is_dotfile(it):
                continue
            mode = get(it["facts"], "mode", "")
            perms = f', permissions = {q("0" + mode)}' if mode in ("600", "400") else ""
            out.append(f'{q(it["facts"]["path"])} = {{ source = {q(self.src_home(it, mod))}, mode = "copy"{perms} }}')
        return out

    def task_lines(self, items) -> list[str]:
        lines = []
        links = [f'ln -sfn "{self.as_home(it["facts"]["target"])}" "{self.as_home(it["facts"]["path"])}"'
                 for it in items if it["kind"] == "link"]
        if links:
            lines += ['mkdir -p "$HOME/.local/bin" "$HOME/bin"'] + links
        for it in items:
            if it["kind"] == "plugin" and it["facts"].get("deploy") in ("rsync", "link"):
                lines.append(f'rsync -ac --delete "{self.as_home(it["facts"]["source"])}/" "{self.as_home(it["facts"]["path"])}/"')
        for it in items:
            if it["kind"] == "plugin" and it["facts"].get("deploy") == "clone":
                src = re.sub("^" + re.escape(self.home), "$HOME", re.sub(r"^file://", "", it["facts"]["url"]))
                dest = self.as_home(it["facts"]["path"])
                lines.append(f'[ -d "{dest}" ] || git clone "{src}" "{dest}"')
        for it in items:
            raw = get(it["facts"], "url", "")
            if self.is_git(it) and raw and (not self.reachable(it) or needs_login(raw)):
                url, dest = clone_url(raw), self.as_home(it["facts"]["path"])
                why = ("could not be reached when this was generated" if not self.reachable(it)
                       else "needs a login or key of its own")
                lines += [f"# {url} {why}. Try it without asking, but never fail on it:",
                          "# the restore lists it for afterwards.",
                          f'if [ ! -d "{dest}" ]; then',
                          f'  GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes" git clone --quiet {q(url)} "{dest}" 2>/dev/null ||',
                          f'    echo {q(f"Clone {url} into {dest}")} | tee -a "${{LATER_FILE:-/dev/null}}"',
                          "fi"]
        lines += [f'mise use -g {q(it["facts"]["mise"])}' for it in items if it["kind"] == "tool"]
        for it in items:
            if it["kind"] == "package-removed":
                lines += ["# Removed on the source machine. Uncomment to remove it here too:",
                          f'# sudo pacman -Rns --noconfirm {it["name"]}']
        return lines

    def toml(self, mod: str) -> str:
        items = self.mine(mod)
        if mod == "":
            host = get(self.inv.get("machine") or {}, "hostname", "this machine")
            parts = [f"# Generated by omarchy-blueprint from {host} on {self.today}.\n"
                     "# Edit freely: regenerating is not meant to happen again. Hardware-specific\n"
                     f"# config lives in mise.<module>.toml.\nmin_version = {q(get(self.inv, 'mise', '2026.10.25'))}"]
        else:
            parts = [f"# The {mod} module: only machines whose modules/{mod}/detect matches.\n"
                     "# bootstrap.sh offers it there and records the choice in miserc.local.toml."]
        if p := self.packages(items):
            parts.append("[bootstrap.packages]\n" + "\n".join(p))
        if f := self.files(items, mod):
            parts.append("\n\n".join(f))
        if s := self.services(items):
            parts.append("\n\n".join(s))
        if r := self.repos(items):
            parts.append("# Only repos the desktop runs from. Clone development checkouts by hand.\n[bootstrap.repos]\n" + "\n".join(r))
        if d := self.dotfiles(items, mod):
            parts.append("# Copies, never symlinks: Omarchy and apps rewrite their own configs.\n[dotfiles]\n" + "\n".join(d))
        return "\n\n".join(parts) + "\n"

    def copies(self, mod: str) -> list[tuple[str, str, bool]]:
        """(source on this machine, destination in the repo, needs sudo)."""
        out = []
        for it in self.mine(mod):
            f = it["facts"]
            if it["kind"] == "system-file":
                out.append((it["name"], self.src_etc(it, mod), f.get("readable") is False))
            elif it["kind"] in ("user-unit", "command") or self.is_dotfile(it):
                out.append((self.abs(f["path"]), self.src_home(it, mod), False))
        return out


# Writing the repo ----------------------------------------------------------

def merge(inventory: dict, decisions: dict) -> dict:
    """Decisions on top of the inspector's suggestions."""
    dec = decisions.get("decisions") or {}
    items = []
    for it in inventory["items"]:
        d = dec.get(it["id"])
        if d:
            it = {**it, "class": d["class"], "module": get(d, "module", it["module"])}
            if d.get("first"):
                it["first"] = True
        items.append(it)
    return {**inventory, "items": items}


def detect_script(mod: str, machine: dict) -> str:
    vendor, product, cpu = (get(machine, k, "") for k in ("vendor", "product", "cpu"))
    checks = [f"[[ $(cat /sys/class/dmi/id/sys_vendor 2>/dev/null) == {shell_word(vendor)} ]]"]
    if product:
        checks.append(f"[[ $(cat /sys/class/dmi/id/product_name 2>/dev/null) == {shell_word(product.split(' (')[0])}* ]]")
    if cpu == "intel":
        checks.append("grep -q GenuineIntel /proc/cpuinfo")
    if cpu == "amd":
        checks.append("grep -q AuthenticAMD /proc/cpuinfo")
    return ("#!/usr/bin/env bash\n"
            f"# about: {vendor} {product}\n"
            f"# Exit 0 on machines the {mod} module fits. Written from the machine it was\n"
            "# made on: loosen or tighten the match by hand.\n"
            + " &&\n  ".join(checks) + "\n")


def mise_toml(b: Build, modules: list[str]) -> str:
    out = b.toml("") + "\n"
    base_task = "\n".join(b.task_lines(b.mine("")))
    module_task = ""
    for m in modules:
        lines = b.task_lines(b.mine(m))
        if lines:
            module_task += f"\nif modules/{m}/detect; then\n" + "\n".join("  " + x for x in lines) + "\nfi"
    if base_task + module_task:
        out += ("\n# Runs at the end of every mise bootstrap, so it must stay safe to repeat.\n"
                "# Links and plugin copies are here, not in [dotfiles]: their targets only exist\n"
                "# once repos are cloned. Plugins are copied, not linked, because Omarchy's hot\n"
                "# reload does not follow symlinks.\n"
                "[tasks.bootstrap]\n"
                'description = "Link commands and deploy plugins"\n'
                "run = '''\n"
                f"{base_task}{module_task}\n"
                "'''\n")

    # Folders carried as dotfile copies: mise dot add does not notice edits
    # inside them, so sync copies them back by hand.
    out += ("\n# Copy live edits back into this repo. Review with git diff, then commit.\n"
            "[tasks.sync]\n"
            'description = "Copy live edits back into this repo"\n'
            "run = '''\n")
    for it in b.items:
        if it["class"] in ("carry", "module") and ((it["kind"] == "plugin" and it["facts"].get("deploy") == "copy")
                                                   or it["kind"] == "config-dir"):
            d = it["facts"]["path"]
            root = f"modules/{it['module']}/" if it["class"] == "module" else ""
            out += (f"rsync -a --delete --exclude='*.bak*' --exclude=.git \"{re.sub(r'^~', '$HOME', d)}/\" "
                    f"\"{root}home/{d.removeprefix('~/')}/\"\n")
    out += "mise dot add --changed --yes\n'''\n"
    return out


AUR_HELP = r"""
## A package that no longer builds

AUR packages break when Arch updates something they depend on. `bootstrap.sh`
then names the package, applies everything else and asks for a rerun. To fix it:

1. Look at the package's AUR page: comments usually name the cause, and
   upstream often has a fix that is not released yet.
2. Put a PKGBUILD that builds in `pkgbuilds/<name>/PKGBUILD`: the AUR one, pinned to
   the commit with the fix (`yay -G <name>` fetches it). Say at the top how to undo it.
3. Remove `"aur:<name>"` from `[bootstrap.packages]`, and build it last in
   `[tasks.bootstrap]`:

   ```sh
   if ! pacman -Q <name> >/dev/null 2>&1; then
     build=$(mktemp -d)
     cp pkgbuilds/<name>/PKGBUILD "$build/"
     # makepkg asks for the password again for every pacman call (sudo -k). Plain
     # sudo lets it use the one the restore already has.
     printf '%s\n' 'source /etc/makepkg.conf' \
       'for c in /etc/makepkg.conf.d/*.conf; do [[ -r $c ]] && source "$c"; done' \
       'PACMAN_AUTH=(sudo)' >"$build/makepkg.conf"
     # A failed build is listed for afterwards rather than stopping the task:
     # the lines after it (another pinned package) still run.
     (cd "$build" && makepkg --config makepkg.conf --syncdeps --install --rmdeps --needed --noconfirm) ||
       echo "<name> did not build: see pkgbuilds/<name>" | tee -a "${LATER_FILE:-/dev/null}"
     rm -rf "$build"
   fi
   ```

4. Once the AUR package builds again, delete the folder and put the line back.
"""


def readme(name: str, b: Build, modules: list[str]) -> str:
    aur = AUR_HELP if any(it["kind"] == "package" and it["class"] in ("carry", "module")
                          and it["facts"].get("source") == "aur" for it in b.items) else ""
    host = get(b.inv.get("machine") or {}, "hostname", "the source machine")
    notes = "\n".join(f"- **{it['name']}**: {it['reason']}" for it in b.items if it["class"] == "note")
    rows = "".join(f"| `mise.{m}.toml` | The {m} module: only on machines `modules/{m}/detect` matches |\n" for m in modules)
    return (f"""# {name}

My Omarchy setup, applied with `mise bootstrap`. Generated by
[omarchy-blueprint](https://github.com/llstrk/omarchy-blueprint) from {host} on {b.today}.
Omarchy keeps owning its defaults: this repo only carries what differs from them.

Keep this repository private unless you have checked every file in it.

| Path | Contents |
|---|---|
| `mise.toml` | Packages, system files, services, repos and configs for every machine |
{rows}| `bootstrap.sh`, `steps/` | Guided restore. Each step is one file; add, remove or reorder them |
| `home/`, `etc/` | Copies of the carried files, at their paths under `~` and `/etc` |
""" + ("| `modules/` | Per-module files and detect scripts |\n" if modules else "") + f"""
## Restore on a new machine

1. Install Omarchy, log in once so first-run setup finishes, then run `omarchy update`.
2. Fetch this repo and start the guided restore:

   ```sh
   mise use -g gh
   mise x -- gh auth login
   mise x -- gh auth setup-git
   git clone <this repo's URL> ~/Work/{name}
   ~/Work/{name}/bootstrap.sh
   ```

3. `bootstrap.sh` opens in an Omarchy popup and walks through the steps. It shows
   `mise bootstrap plan` and the configs it will replace, and asks before applying them.
4. Log out and back in.

`--check` reports what it would do without changing anything, `--no-popup` runs in
the current terminal and `--only NAME` runs one step. Every step checks whether it
is already done, so the script is safe to run again.

## Day to day

Configs are copies, so editing the live file does not change this repo:

```sh
mise run sync    # copy live edits back in
git diff         # review, then commit
```

To bring repo changes onto a machine: `git pull`, then `mise bootstrap plan` and
`mise bootstrap`.
{aur}
## Not carried here

These need a real backup, or a fresh sign-in on the new machine:

{notes or "- Nothing was marked as a note."}
""")


def fill(recipe: str, marker: str, lines: list[str]) -> str:
    """The recipe with the line holding marker replaced by lines."""
    text = (TEMPLATE / "recipes" / recipe).read_text()
    return "".join("\n".join(lines) + "\n" if marker in line else line for line in text.splitlines(keepends=True))


def write_steps(target: Path, items: list[dict], modules: list[str]) -> None:
    steps = target / "steps"

    def step(n: str, name: str) -> None:
        shutil.copy(TEMPLATE / "recipes" / f"{name}.sh", steps / f"{n}-{name}.sh")

    def has(pred) -> bool:
        return any(pred(it) for it in items)

    def is_step(id_):
        return has(lambda it: it["id"] == id_ and it["class"] == "step")

    step("00", "preflight")
    if any("github.com" in get(it["facts"], "url", "") for it in items if it["class"] not in ("skip", "note")) \
            or is_step("identity:github"):
        step("10", "github")
    if modules:
        step("20", "modules")
    step("30", "trust")
    step("40", "bootstrap")
    # Questions come before mise bootstrap where they can, so the long part
    # runs unattended. Fingerprint and Tailscale need packages it installs.
    if is_step("identity:ssh-keys"):
        step("25", "ssh-keys")
    # The reminder to join the tailnet, when the restore installs Tailscale.
    if is_step("identity:tailscale") and has(lambda it: it["id"] == "package:tailscale"
                                              and it["class"] in ("carry", "module", "step")):
        step("60", "tailscale")
    if is_step("identity:fingerprint"):
        step("70", "fingerprint")

    # Apps from Omarchy's installers come last: the base system first, and apps
    # are easy to add by hand if one fails. Only an app something carried needs
    # during mise bootstrap (a service from its package, a config it would
    # overwrite) runs before it. The agent marks those "first" in decisions.json.
    apps = [it for it in items if it["class"] == "step" and it["kind"] == "package" and it["facts"].get("installer")]
    for n, title, group in (("35", "Apps the setup needs first", [it for it in apps if it.get("first")]),
                            ("80", "Apps", [it for it in apps if not it.get("first")])):
        if group:
            fill_lines = [f'  "{it["name"]} {it["facts"]["installer"]}"' for it in group]
            text = fill("omarchy-installers.sh", "#INSTALLERS#", fill_lines)
            name = "omarchy-installers-first" if n == "35" else "apps"
            (steps / f"{n}-{name}.sh").write_text(text.replace("#TITLE#", f'header "{title}"'))

    # Steps with no recipe become a checklist.
    manual = ["  " + shell_quote(re.sub(r"[^A-Za-z0-9]+", "-", it["id"]) + " " + it["name"] + ": " + it["reason"])
              for it in items if it["class"] == "step" and it["id"] not in STEP_IDS
              and not (it["kind"] == "package" and it["facts"].get("installer"))]
    if manual:
        (steps / "90-manual.sh").write_text(fill("manual.sh", "#MANUAL#", manual))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bin/generate", description=__doc__.split("\n\n")[0],
                                 epilog="\n\n".join(__doc__.split("\n\n")[2:]),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", metavar="TARGET")
    ap.add_argument("--out", default=str(KIT / "out"))
    ap.add_argument("--decisions")
    ap.add_argument("--allow-undecided", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    inv_path = out / "inventory.json"
    if not inv_path.is_file():
        print(f"No {inv_path}. Run bin/inspect first.", file=sys.stderr)
        return 1
    decisions_path = args.decisions or (str(out / "decisions.json") if (out / "decisions.json").is_file() else "")
    target = Path(os.path.abspath(args.target))
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"{args.target} is not empty. Pick a new folder, or pass --force to write into it.", file=sys.stderr)
        return 1
    target.mkdir(parents=True, exist_ok=True)

    inventory = json.loads(inv_path.read_text())
    if decisions_path:
        decisions = json.loads(Path(decisions_path).read_text())
        inventory = merge(inventory, decisions)
        print(f"Applied {len(decisions.get('decisions') or {})} decisions from {decisions_path}")
        made_for = decisions.get("inventory") or ""
        if made_for and made_for != inventory.get("generated"):
            print(f"Warning: these decisions were made for an earlier inspection ({made_for}).\n"
                  "  Items that changed since keep the inspector's suggestion. Review them in bin/blueprint.", file=sys.stderr)

    undecided = [it for it in inventory["items"] if it["class"] == "review"]
    if undecided:
        if not args.allow_undecided:
            print("These items still need a decision (open the blueprint, or pass --allow-undecided):", file=sys.stderr)
            for it in undecided:
                print(f"  {it['kind']}  {it['name']}", file=sys.stderr)
            return 1
        print(f"Leaving out {len(undecided)} undecided items.")
        inventory["items"] = [{**it, "class": "skip"} if it["class"] == "review" else it for it in inventory["items"]]

    items = inventory["items"]
    modules = sorted({it["module"] for it in items if it["class"] == "module"})

    # The bootstrap task copies plugins with rsync, which a fresh Omarchy may lack.
    if any(it["class"] in ("carry", "module") and it["kind"] == "plugin" and it["facts"].get("deploy") in ("rsync", "link")
           for it in items) and not any(it["id"] == "package:rsync" and it["class"] == "carry" for it in items):
        items.append({"id": "package:rsync", "kind": "package", "name": "rsync", "class": "carry", "module": None,
                      "reason": "The bootstrap task copies plugins with rsync.", "facts": {"source": "pacman"}})

    # A carried service needs its package on the new machine before mise's
    # services phase runs. Warn when nothing carries that package.
    have = {it["name"] for it in items if it["kind"] == "package" and it["class"] in ("carry", "module", "step")}
    unhoused = [f"  {it['name']} comes from {it['facts']['package']}, which nothing installs" for it in items
                if it["kind"] == "service" and it["class"] in ("carry", "module") and it["facts"].get("package")
                and it["facts"]["package"] not in have]

    b = Build(inventory, os.environ.get("HOME", str(Path.home())), date.today().isoformat())
    (target / "mise.toml").write_text(mise_toml(b, modules))
    machine = inventory.get("machine") or {}
    for m in modules:
        (target / f"mise.{m}.toml").write_text(b.toml(m) + "\n")
        detect = target / "modules" / m / "detect"
        detect.parent.mkdir(parents=True, exist_ok=True)
        detect.write_text(detect_script(m, machine))
        detect.chmod(0o755)

    copied, needs_sudo, missing = 0, [], []
    for m in ["", *modules]:
        for src, dest, sudo in b.copies(m):
            to = target / dest
            to.parent.mkdir(parents=True, exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, to, symlinks=True, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("*.bak*", ".git"))
                copied += 1
            elif not os.path.lexists(src):
                missing.append(src)
            elif sudo or not os.access(src, os.R_OK):
                needs_sudo.append(f"sudo cat {shell_word(src)} > {shell_word(str(to))}")
            else:
                shutil.copy2(src, to)
                copied += 1

    (target / "steps").mkdir(exist_ok=True)
    (target / "lib").mkdir(exist_ok=True)
    shutil.copy(TEMPLATE / "bootstrap.sh", target / "bootstrap.sh")
    shutil.copy(TEMPLATE / "lib/ui.sh", target / "lib/ui.sh")
    (target / "bootstrap.sh").chmod(0o755)
    write_steps(target, items, modules)
    (target / "README.md").write_text(readme(target.name, b, modules))
    (target / ".gitignore").write_text("*.bak*\n")

    steps = " ".join(re.sub(r"\.sh$", "", re.sub(r"^[0-9]*-", "", p.name))
                     for p in sorted((target / "steps").glob("*.sh")))
    print(f"\nWrote {target}")
    print("  mise.toml" + "".join(f", mise.{m}.toml" for m in modules))
    print(f"  {copied} files and folders copied")
    print(f"  steps: {steps}")
    if unhoused:
        print("\nServices whose package is not carried (mise bootstrap will fail on them):")
        print("\n".join(unhoused))
    if missing:
        print("\nMissing on this machine (left out):")
        print("\n".join(f"  {m}" for m in missing))
    if needs_sudo:
        print("\nOnly root can read these. Copy them in, then make them yours:")
        print("\n".join(f"  {c}" for c in needs_sudo))
        print(f"  sudo chown -R {os.environ.get('USER', '')}: {shell_word(str(target))}")
    print()
    scan_secrets.main([str(target)])
    return 0
