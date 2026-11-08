# Omarchy Blueprint: agent playbook

You are turning one person's existing Omarchy install into a setup repo they
can restore on any machine with `mise bootstrap`. The repo should carry only
what differs from stock Omarchy, be easy to read and edit by hand, and come
with a guided `bootstrap.sh` for what cannot live in a repo.

The person decides what gets carried. You do the inspecting, propose decisions
with reasons, show them in the blueprint page, and build from their answers.
Everything else is yours to run: the person should only need to give you this
repo's address, review the page, and answer what is genuinely theirs.

If you were pointed at this repo by its address, work from a clone, not the web
page. Clone it, or update the clone that is already there, and continue from
the `AGENTS.md` in it:

```sh
git clone https://github.com/llstrk/omarchy-blueprint.git ~/Work/omarchy-blueprint ||
  git -C ~/Work/omarchy-blueprint pull --ff-only
cd ~/Work/omarchy-blueprint
```

The setup repo goes to `~/Work/my-omarchy` unless the person names another place.

## Ground rules

- **Inspecting is read-only.** Until the generate phase, do not change anything on the machine.
  The collectors in `omarchy_blueprint/collectors/` only read. Do not run `mise bootstrap` (without
  `plan` or `--dry-run`), `mise dot apply`, `omarchy refresh` or anything with sudo
  that writes.
- **Never carry secrets.** That covers private keys, tokens, `gh` hosts files, Tailscale state,
  Wi-Fi passwords, `.netrc` and browser profiles. Read a small file before you propose
  carrying it. `bin/check-secrets` must come back clean before you commit.
- **Never publish.** Do not create remote repos, push or upload without the person asking
  in so many words. The generated repo holds names, hosts and paths: suggest a
  private repo.
- **Stop and ask** when a decision is genuinely theirs: what an app folder is, whether a
  removed package was deliberate, whether a repo is something they still use.
  Do not ask about what the rules in `docs/classify.md` already settle.
- **Write for a person.** Comments in generated files say why, not what. Do not use
  em dashes.

## How a restore runs

The generated `bootstrap.sh` puts the base system in place as fast as possible
and needs the person as little as possible. Keep it that way when you add steps
or task lines:

1. **Questions first.** GitHub sign-in, hardware modules, an SSH key, trust, then
   "Apply all of this now?". A question that needs nothing installed goes in a step
   numbered below 40.
2. **The password once,** right after that answer (`need_sudo` in `lib/ui.sh`). The
   whole run is one terminal, and sudo remembers the password per terminal, so never
   wrap a command in `script` or another terminal. Call `need_sudo` before the first
   sudo in a step of your own. makepkg asks again for every pacman call unless it
   gets `PACMAN_AUTH=(sudo)`: use the build recipe in `docs/packages.md`.
3. **Then the base system, unattended:** `mise bootstrap` installs the packages,
   files, services, repos and configs, then runs the task.
4. **Nothing waits on the person after that.** A login, a pairing or a finger on a
   reader is never run mid-restore: the step checks it and hands the command to
   `later`, and the run ends with that list. GitHub sign-in is the one exception,
   at the start, because private repos need it. Do not carry an installer that
   signs in (Omarchy's Tailscale installer runs `tailscale up`): carry its package
   and service instead.
5. **Apps last** (`steps/80-apps.sh`), the installers that ask a question first.
   Phase 3 covers the rare app that has to come before `mise bootstrap`.

## Phases

### 1. Check the machine

```sh
cat /usr/share/omarchy/version; pacman -Q omarchy; mise --version; python3 --version
```

You need Omarchy 4 or newer, mise 2026.10.25 or newer (`mise bootstrap`) and
Python 3.11 or newer (every Omarchy install has it).
If mise is older, tell the person to run `omarchy update` first.

### 2. Inspect

```sh
bin/inspect               # about 5 seconds, writes out/inventory.json
bin/inspect --offline     # skip checking whether repo remotes can be reached
bin/inspect --only NAME   # one collector, printed as JSON lines
```

Each collector prints how many items it found. If one fails, the traceback says
where: fix the cause if it is in this repo, add a test for it, and say so.

Every item has a `class`, the inspector's suggestion:

| Class | Meaning | Ends up in |
|---|---|---|
| `carry` | Yours, and safe to restore everywhere | `mise.toml` |
| `module` | Yours, but only for this hardware | `mise.<module>.toml` |
| `step` | Needs a person or a login on the new machine | `bootstrap.sh` steps |
| `note` | Cannot be carried (secrets, app data, personal files) | README "Not carried here" |
| `skip` | Omarchy's own, state, caches, backups | nowhere |
| `review` | The inspector cannot tell | your proposal, then theirs |

`docs/inventory.md` describes every field.

### 3. Propose decisions

The inspector only finds candidates. This pass is where the sorting happens:
read every `review` file and every `carry` file, and leave out by default
anything the person did not choose. Common cases:

- state an app rewrites (sessions, recent files, window sizes, caches)
- files an app or Omarchy writes itself (integrations, first-login files, hooks)
- defaults that only look edited (a lockfile, a config an upgrade rewrote)
- files nothing loads any more
- tools that point into a folder only this machine has

Apps from Omarchy's installers (packages that are a `step` with an `installer`)
run last, after the base system is in place: the base system matters most, and
an app that fails is easy to add by hand. Check each one for whether
`mise bootstrap` needs it first:

- a carried service or user unit that comes from its package
- a carried config the installer writes too, which it would overwrite afterwards
- a line in the bootstrap task that runs it or reads its files

Only then add `"first": true` to its decision and say in `why` what needs it
("tailscaled is carried and comes from this package."). Expect none.

Use `docs/classify.md`. For each one you settle, add an entry to
`out/decisions.json` with a short reason the person will read:

```json
{
  "schema": 1,
  "inventory": "<generated timestamp from inventory.json>",
  "decisions": {
    "config:~/.config/herdr/session.json": { "class": "skip", "why": "Session state herdr rewrites on exit." },
    "service:rapl-pl1.service": { "class": "module", "module": "framework", "why": "A power limit tuned for this laptop's CPU." }
  }
}
```

Read the file before proposing to carry it. Its `facts.path` in `out/inventory.json`
says where it is. Leave items you cannot settle as `review` for the person.

Hardware modules: one per kind of machine, named after it (`framework`,
`thinkpad`), never per host. Start from `machine` in `out/inventory.json`
(vendor, product, CPU, GPUs, laptop, fingerprint reader, touchscreen,
monitors) and ask of every item you carry: would this be wrong or useless on
different hardware? The inspector only flags `monitors.lua` by itself, so the
rest is yours to find. Things that belong in a module include per-machine
displays, power and lid tweaks (RAPL limits, `logind.conf.d`), fixes for the
fingerprint reader, vendor tools, and scripts or units that support them. Not
the fingerprint packages: Omarchy's fingerprint setup installs those when the
person enrolls a finger, in the build it picks.
Peripherals follow the person, not the laptop: a keyboard's udev rule or a tool
for an external monitor is carried everywhere. If nothing is
hardware-specific, use no modules. Say in each `why` what ties the item to
this hardware ("Only this laptop has a fingerprint reader.").

### 4. Show the blueprint

```sh
bin/blueprint        # serves the page and opens it; ends when they press Done
```

Run it in the background: it serves the page on this machine only, saves every
choice to `out/decisions.json` as the person makes it, and exits when they press
Done, printing how many choices are theirs. Wait for that, then go on to
generate. If they tell you they are finished without pressing Done, the file is
already saved: stop the command and go on.

The page lists every item grouped by kind, with the inspector's reason and
yours. The tree on the left shows the repo that will be built, and it updates as
the person changes decisions. Tell them:

- The "To decide" tab has everything that needs their eye, including your proposals.
- Each item is a card with its name and its choices, so they can decide without
  opening it. Clicking the name shows what it is, your reason, what happens on a
  new machine (hovering a choice previews it) and the facts. The tree follows
  every change.
- Clicking a line in the tree filters to the items that land there.
- Their choices save as they go. When they are finished, they press Done.

Choices they made are marked `"by": "you"`. If they say your proposals are
fine, they press Done without changing anything.

### 5. Generate

```sh
bin/generate ~/Work/my-omarchy          # stops if anything is still "review"
bin/generate --allow-undecided DIR      # leaves undecided items out
```

It writes `mise.toml`, `mise.<module>.toml`, copies of the carried files under
`home/`, `etc/` and `modules/<module>/`, `bootstrap.sh` with steps chosen from
`template/recipes/`, and a README. Then deal with what it reports:

- **Files only root can read:** run the printed `sudo cat` commands only with the person's
  go-ahead, then `chown` the repo back to them.
- **Services whose package is not carried:** carry the package, or drop the service.
  `mise bootstrap` fails on a unit that does not exist.
- **Secrets:** remove the file or the line. Never commit past a strong match.

### 6. Finish by hand

The generator gets the structure right. These need judgment:

- **The bootstrap task:** add steps an app's own setup needs (an `install -D` of a
  data file, a command that registers something). Keep every line safe to
  repeat.
- **Broken AUR packages:** if a package will not build today, carry a local PKGBUILD and
  build it in the task. See `docs/packages.md`.
- **App setup the person runs once** (a pairing command, a login): add a step in
  `steps/` after 40 that checks whether it is done and otherwise hands the command
  to `later`. Copy the shape of `template/recipes/tailscale.sh`. Never run it in
  the restore: see "How a restore runs".
- **The README "Not carried here" list:** group the notes so a person can act on them.

### 7. Verify on this machine

The source machine already has everything, so the generated repo must be a
no-op here:

```sh
cd ~/Work/my-omarchy
export MISE_TRUSTED_CONFIG_PATHS="$PWD:$HOME/.config/mise"
MISE_ENV=framework mise bootstrap plan          # want: 0 create, 0 update
MISE_ENV=framework mise bootstrap --dry-run     # want: nothing but the task
./bootstrap.sh --check --no-popup               # every step reads cleanly
mise x shellcheck@0.11.0 -- shellcheck -x bootstrap.sh lib/*.sh steps/*.sh modules/*/detect
~/Work/omarchy-blueprint/bin/check-secrets .
```

Set `MISE_ENV` to the modules this machine uses (empty for none). Anything in
the plan besides `unchanged` means a copy differs from the live file or a path
is wrong. Fix the generated repo, never the machine.

Then check that every AUR package still builds. A package that built here
months ago can fail today, and otherwise only the new machine finds out:

```sh
~/Work/omarchy-blueprint/bin/check-builds ~/Work/my-omarchy
```

It runs each package's build script, so ask the person before running it on
their machine (a spare machine or VM is better). For one that fails, find the
cause (the AUR comments, upstream's issues and commits) and pin a PKGBUILD as in
`docs/packages.md`, then run the check again.

### 8. Hand over

`git init`, commit, and tell the person:

- what is carried and what is not, in a few lines
- how to restore: `docs/restore.md` has the steps for a new machine. The questions
  come in the first minute, then the password once, and the run ends with a list
  of what is left for them (Tailscale, fingerprint, anything that failed)
- what was not verified (anything only a fresh install can show)

Then offer to put it on GitHub as a private repo. The new machine needs it
from somewhere: `docs/restore.md` starts with cloning it from GitHub. Ask, and
wait for a clear yes. **Never create the repo or push on your own**, not even as
the obvious next step and not with a default name: it is their account and
their data. When they agree, check the name with them and run:

```sh
gh repo create <name> --private --source . --push
```

If they would rather keep it off GitHub, tell them how else to get it onto the
new machine: copy the folder (a USB stick), or `git bundle create setup.bundle --all`
and clone from that file. Then `docs/restore.md` applies from the clone.

## When a restore fails

`docs/troubleshooting.md` lists the failures seen in practice with their
fixes: sudo without a terminal or asking again and again, gh asking to sign in again, AUR builds,
unreachable repos, and mise prompting for every config.

## Files in this repo

| Path | What it is |
|---|---|
| `bin/` | `inspect`, `blueprint`, `generate` and `check-secrets` (launchers for the package), and `check-builds` |
| `omarchy_blueprint/` | The Python package (standard library only). `collectors/` hold the rules |
| `blueprint/index.html` | The review page template. `bin/blueprint` fills it in |
| `template/` | `bootstrap.sh`, its helpers and the step recipes it is built from |
| `docs/` | Rules and lessons the steps above refer to |
| `tests/` | Rules tested against a fake machine: `python3 -m unittest discover tests` |
| `examples/` | A made-up inventory to try the page with |
