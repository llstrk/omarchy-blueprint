# Validating a change

Every change goes through a pull request, and every check runs on our own
hardware: nothing depends on a hosted CI. There are two tiers.

| Tier | When | Takes |
|---|---|---|
| `bin/check` | every change, before every push | under a minute |
| A restore on a blank VM | changes to the restore: `template/`, `generate.py`, the recipes | about 8 minutes |

Paste what they print into the pull request (the template asks for it).

The tools are Python (standard library only, like the kit): `bin/check` is
`omarchy_blueprint/check.py`, `bin/check-builds` is `check_builds.py`, and the
commands in `tests/vm/` are launchers for `tests/vm/harness.py`. Bash is left
for what has to be bash: the template, the guest setup, the git hook.

## bin/check

```sh
git config core.hooksPath .githooks   # once per clone: runs bin/check before every push
bin/check                             # by hand
bin/check --quick                     # skip generating a repo from out/
```

It checks the kit:

- the unit tests (`tests/`), including the parsing the tools below rely on
- that every Python file compiles
- shellcheck on the template and the kit's few bash scripts
- that the page's script parses (with node, when it is installed)
- no em dashes
- no secrets in what git would commit; the lines it only warns about are printed
  so someone reads them

Then, when `out/` holds an inspection and decisions (`bin/inspect`, then
`bin/blueprint`), it generates a setup repo from them into a temporary folder
and checks it the way AGENTS.md phase 7 does: on the machine it came from, it
must be a no-op.

- `mise bootstrap plan` is empty (0 create, 0 update), with the modules this
  machine matches
- `mise bootstrap --dry-run` shows nothing but the task
- `bootstrap.sh --check --no-popup` offers nothing
- shellcheck and the secret scan pass on the generated repo

A plan that is not empty usually means a file changed since the inspection.
Run `bin/inspect` again: the decisions carry over.

## A restore on a blank VM

`tests/vm/` drives an Omarchy VM through a real restore: it opens a terminal,
starts `bootstrap.sh` in the popup, answers the questions from
`tests/vm/answers.default`, types the password when sudo asks, and prints a
timeline with checks afterwards.

```sh
bin/generate ~/Work/test-setup && git -C ~/Work/test-setup init -q &&
  git -C ~/Work/test-setup add -A && git -C ~/Work/test-setup commit -qm test
VM=2 tests/vm/fresh                        # boots a blank copy of the clean install
VM=2 tests/vm/restore ~/Work/test-setup    # the restore, start to finish
VM=2 tests/vm/stop
```

`VM=2` runs a second instance on ssh port 2223, next to a first one someone may
be using by hand (2222). `fresh` never replaces a running VM.

A good run looks like this: the questions in the first minute, sudo asked once,
`finished, exit 0`, then the "Left for you" list the restore ended with, and
checks on the restored machine:

```
  7:18  finished, exit 0: 8 questions, sudo asked 1 times
        Left for you:
          • Sign in to GitHub (gh auth login), then run ./bootstrap.sh again for the private repos
          • wl-kbptr did not build: see "A package that no longer builds" in README.md
        ✓ plan: 1 create, 0 update, 15 unchanged, 0 remove, 0 unknown
            create     package:aur:wl-kbptr    missing    installed   (on the Left for you list)
        ✓ pending: 1
        ✓ failed units: 0
        ✓ Hyprland config errors: 0
        ✓ left running: 0
```

Work the restore did not finish passes when the "Left for you" list names it: a
package that no longer builds is the restore telling the person, as it should.
Work left undone without a word fails the run.

It exits with `bootstrap.sh`'s exit code, or 2 for an unknown question, 3 when
the popup lost the keyboard, 4 when a check afterwards failed, 1 on a timeout.

An unknown question stops the run with the VM left as it is: add a line to the
answers file if the question is expected. `tests/vm/ssh` opens a shell in the VM
for a look around (`tests/vm/ssh 'command'` runs one), and `tests/vm/qmp shot
screen.png` takes a screenshot. Every command takes `--help`.

### Failures worth testing on purpose

Copy the setup repo, break one thing, commit, and restore it. Each should end
with `exit 0`, the problem on the "Left for you" list and every check passing:

- a package that no longer exists: add `"pacman:no-such-package-xyz" = "latest"`
  under `[bootstrap.packages]`
- a repo that cannot be cloned: change one URL in `[bootstrap.repos]`
- the GitHub sign-in declined: the default answers already do this

### Setting up the VM once

Everything that belongs to the machine lives in `~/VMs/omarchy-test`
(`OMARCHY_VM_DIR` to move it), never in this repo:

| File | What |
|---|---|
| `disk.qcow2`, `OVMF_VARS.fd` | the clean install; test runs use throwaway copies |
| `vm_key`, `vm_key.pub` | an ssh key only for the VM |
| `local.env` | `VM_PASSWORD=...`, the VM's own disk and sudo password (make one up, use it nowhere else); optionally `MIRROR_GITHUB_USER=...` |
| `serve/` | what the VM fetches from this machine at 10.0.2.2:8765 |
| `serve/git/*.git` | optional bare copies of private repos, so the VM needs no GitHub login |

1. `mkdir -p ~/VMs/omarchy-test && ssh-keygen -t ed25519 -N '' -C omarchy-test-vm -f ~/VMs/omarchy-test/vm_key`
2. Write `local.env` with `VM_PASSWORD=` and the password you will give the install.
3. `tests/vm/run install ~/Downloads/omarchy-<version>.iso` and install Omarchy
   with that password, user `user`. Then `tests/vm/run base` and run `omarchy update`.
4. Serve the key and the guest setup, then run it in the VM's terminal:
   ```sh
   mkdir -p ~/VMs/omarchy-test/serve && cp tests/vm/setup-guest ~/VMs/omarchy-test/vm_key.pub ~/VMs/omarchy-test/serve/
   (cd ~/VMs/omarchy-test/serve && python3 -m http.server 8765 --bind 127.0.0.1 &)
   # in the VM:  curl -s 10.0.2.2:8765/setup-guest | bash
   ```
5. Shut the VM down. From now on `tests/vm/fresh` starts from this state.

For private repos the setup repo clones, put bare copies in `serve/git`
(`git clone --bare https://github.com/<you>/<repo>.git serve/git/<repo>.git`, then
`git -C serve/git/<repo>.git update-server-info` so plain HTTP can serve it) and
set `MIRROR_GITHUB_USER=<you>` in `local.env`.

## Not covered yet

- The page in a real browser (clicking a choice, Done): tested by hand so far.
- A fresh agent working from AGENTS.md alone, with nothing but the repo address.
- A restore onto real hardware (fingerprint reader, hardware modules).
