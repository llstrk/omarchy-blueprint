# omarchy-blueprint

Turn the Omarchy install you have into a setup repo you can restore anywhere.

> **Coding agents:** clone this repo and follow [`AGENTS.md`](AGENTS.md) in the
> clone, from its first line. It is the whole process; this page only introduces it.

You have spent months making Omarchy yours: packages, keybindings, a udev rule
for your keyboard, a lid tweak for your laptop, shell plugins, a dozen small
scripts. omarchy-blueprint finds all of it, shows you a plan, and builds a
[`mise bootstrap`](https://mise.jdx.dev/bootstrap.html) repo from your choices.
That repo comes with a guided `bootstrap.sh`, which restores it on a fresh
machine one question at a time.

It is written to be driven by a coding agent (Claude Code, Codex, opencode).
The agent follows [`AGENTS.md`](AGENTS.md): it inspects, proposes, shows you the
blueprint, and builds the repo. Everything also works by hand.

## How it works

```text
bin/inspect      reads the machine, writes out/inventory.json     (changes nothing)
bin/blueprint    shows it as a page: what gets carried, and where (you decide)
bin/generate     builds the setup repo from your decisions
bootstrap.sh     restores it on a new machine, step by step
```

The inspector compares the machine with what Omarchy itself installs: its package
lists and installers, `/etc/skel`, its shipped configs, the files and services
its scripts name. What is left is yours. Every item gets a class and a reason:

- **carry** goes to `mise.toml`
- **module** goes to `mise.<module>.toml`, only on matching hardware
- **step** becomes a guided step: GitHub sign-in at the start, Omarchy's own installers
  at the end, and logins or enrollments listed for afterwards
- **note** is listed as not carried: secrets, app data, personal files
- **skip** is Omarchy's, or state
- **review** waits for a decision

## With an agent

Tell your coding agent:

> Make a blueprint of this Omarchy machine with https://github.com/llstrk/omarchy-blueprint

That is all. It clones the kit, inspects the machine and proposes what to carry.
Then it opens the blueprint page: change anything you like (it saves as you
go) and press Done. It builds the repo in `~/Work/my-omarchy` and checks it
against this machine. Agents: start with [`AGENTS.md`](AGENTS.md).

## By hand

```sh
git clone https://github.com/llstrk/omarchy-blueprint.git
cd omarchy-blueprint
bin/inspect                       # about 5 seconds
bin/blueprint                     # decide, then press Done in the page
bin/generate ~/Work/my-omarchy
```

To see the page without inspecting anything: `bin/blueprint --static --out examples`.

## What you get

```text
my-omarchy/
├── mise.toml              packages, /etc files, services, repos, configs, tasks
├── mise.framework.toml    one per hardware module
├── bootstrap.sh           guided restore, opens as an Omarchy popup
├── steps/                 one file per step: add, remove or reorder them
│   ├── 00-preflight.sh
│   ├── 10-github.sh
│   ├── 20-modules.sh      offers modules whose detect script matches
│   ├── 25-ssh-keys.sh     questions first, so the long part runs unattended
│   ├── 30-trust.sh
│   ├── 40-bootstrap.sh    shows the plan, asks for the password once, runs mise bootstrap
│   ├── 70-fingerprint.sh  ... and your own steps that need what mise installed
│   └── 80-apps.sh         apps from Omarchy's installers, last
├── lib/ui.sh              helpers the steps share
├── modules/framework/     detect script and module files
├── home/  etc/            copies of the carried files
└── README.md              restore steps, and what is not carried
```

The generated repo is plain mise config and short shell scripts. Read it, edit
it, and commit it. You only generate once: after that it is your repo.

## What it has learned

[`docs/`](docs) holds the rules the agent follows and the failures they came
from:

- [`classify.md`](docs/classify.md): what to carry, as a module, as a step, or not at all
- [`mise-bootstrap.md`](docs/mise-bootstrap.md): phase order, copies versus links, sudo
  in scripts, oneshot services
- [`plugins.md`](docs/plugins.md): one plugin per repo, hot reload, deploying from a project
- [`packages.md`](docs/packages.md): Omarchy's installers, broken AUR builds, sources that
  vanish
- [`troubleshooting.md`](docs/troubleshooting.md): failures seen on real restores
- [`inventory.md`](docs/inventory.md): the inventory format, and how to add a collector

## Privacy

Inspection is local and read-only. `out/` is ignored by git. The blueprint is a
local file that uploads nothing. Only names, paths and counts of secrets are
recorded, never their contents. The generated repo contains your configs, so
keep it private, and run `bin/check-secrets` on it before every commit.

## Status

Early. Built on Omarchy 4.0 and tested restoring onto 4.5, with mise 2026.10.25 or newer. Omarchy is still
changing quickly, and so will this.

The kit is Python 3.11 or newer with only the standard library, which every Omarchy
install already has. The generated repo is mise config and short shell scripts, so
it needs nothing extra either. Tests run against a fake machine:
`python3 -m unittest discover tests`.

## Related

[Omarchy dots](https://github.com/omacom/omarchy/pull/14452) (proposed) keeps a
history of your config files and syncs them between machines with mise. It covers
configs only: packages, system files, services, repos, plugins and hardware
are not part of it. When it is on, the inspector leaves the files it tracks to it.

## License

MIT, like Omarchy. See [LICENSE](LICENSE).
