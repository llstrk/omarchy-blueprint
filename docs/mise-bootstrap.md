# mise bootstrap, as used here

Notes from building and restoring real setups with mise 2026.10.25. The
official reference is <https://mise.jdx.dev/bootstrap.html>.

## Order

`mise bootstrap` applies, in order: packages, system files, services, repos,
dotfiles, tools, then the `bootstrap` task. That order decides where things go:

- **User unit files go in `[bootstrap.files]`, not `[dotfiles]`.** Files apply before
  services, dotfiles after. A user service whose unit is a dotfile does not exist yet
  when mise tries to start it.
- **Links into repos go in the task, not `[dotfiles]`.** mise checks every dotfile source
  before writing anything, and a repo's files only exist after the repos phase.
- **Plugin deploys go in the task**, for the same reason.
- **Packages a service needs must be carried.** mise does not create system units.

## Config layout

- `mise.toml` holds everything shared. `mise.<module>.toml` holds a module, loaded when
  `MISE_ENV` names it.
- The choice of modules lives in `~/.config/mise/miserc.local.toml` on each machine,
  as `env = ["framework"]` or `env = []`. It is never committed, and the bootstrap
  script writes it.
- Set `min_version` to the mise that generated the repo. Older mise ignores unknown
  sections silently.
- Tasks run from the config root, so `pkgbuilds/...` and `modules/...` paths in the task
  are relative to the repo.
- A task defined in a module file replaces the base task of the same name. Keep one
  `[tasks.bootstrap]` in `mise.toml`, and guard module lines with `if modules/<m>/detect`.

## Trust

mise ignores config in untrusted folders. `mise trust` in the repo, once per
machine. For tests that must not touch trust state, set
`MISE_TRUSTED_CONFIG_PATHS="$PWD:$HOME/.config/mise"`.

## Dotfiles

- **Use `mode = "copy"` for everything Omarchy or an app may rewrite.** That is nearly
  everything under `~/.config`. A symlink gets replaced by `omarchy refresh` or by the
  app, and then the repo and the machine silently differ.
- **In a terminal, mise asks about every config that differs from the repo.** The
  bootstrap script passes `--force-dotfiles` after showing the person the list.
  Without a terminal, mise overwrites copies silently.
- **`mise dot add --changed` and `mise dot status` do not notice edits inside directory
  entries.** The generated `sync` task copies those folders back with `rsync`.
- **`permissions = "0600"`** for anything private, such as `~/.ssh/config`.

## Running it from a script

- **sudo needs a terminal.** Piping `mise bootstrap` through `tee` gives it none, and sudo
  fails with "sudo requires a password but no TTY is available". Log with
  `script(1)` instead, around the whole run: sudo remembers the password per
  terminal, and every `script -c` is a new one that asks again.
- **`--yes` answers mise's own prompts, not sudo's.** The password is still asked for.
- **The bootstrap task runs on every bootstrap.** Every line must be safe to repeat:
  `ln -sfn`, `rsync -ac --delete`, `[ -d X ] || git clone`, `install -D`.
- **A failing line stops the task,** and the bootstrap reports failure. Put anything that
  is allowed to fail (optional clones) before the steps that must succeed, with
  `|| echo ... skipped`.

## Files and services

- **`notify = ["unit"]` on a file restarts that unit when the file changes.** Never use it
  on `logind` files: restarting logind ends the desktop session. Say so in a comment.
- **Oneshot units:** `state = "stopped"`, `enabled = true`. "running" would start them on
  every bootstrap.
- **Masked units:** `state = "stopped"`, `enabled = false`, `masked = true`.
- **Timers and sockets need their full unit name** as the key:
  `[bootstrap.services."backup.timer"]`. A bare name gets `.service`.
- **New udev rules** take effect after a reboot or `sudo udevadm control --reload`. Say so
  in the README rather than reloading in the task.

## Repos

- **Leave `ref` out unless you want to pin.** Without it, existing checkouts keep their
  branch and commit, and new ones clone the default branch.
- **A repo that cannot be cloned fails the whole repos phase.** Only list repos that are
  reachable from a fresh machine with the person signed in. Anything else goes in the
  task, as a clone that is allowed to fail.
- **Private GitHub repos need `gh` signed in before bootstrap**, with `gh auth setup-git`.
  Omarchy does not ship gh: install it with `mise use -g gh`, and put the mise shims
  folder on `PATH` in scripts, because the popup terminal is not an interactive shell.

## Checking a repo without applying it

```sh
mise bootstrap plan        # resource by resource: create, update, unchanged
mise bootstrap --dry-run   # the commands it would run, including the task
mise bootstrap status      # what is in place now
```

On the machine the repo was made from, `plan` should say `0 create, 0 update`.
