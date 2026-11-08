# Deciding what to carry

The inspector suggests a class for every item. These rules settle most of the
`review` items and catch mistakes in the rest. When a rule does not settle it,
ask the person.

## The test

Carry something when all three are true:

1. **It is a choice the person made.** It is not something Omarchy, a package or
   an app put there.
2. **It would be lost on a fresh install.** It is not something Omarchy does again
   by itself.
3. **It is safe to put in a repo.** It holds no secrets, and it is not state an app
   rewrites constantly.

## Packages

- **Explicitly installed and in no Omarchy list:** carry it.
- **Installed by an `omarchy-install-*` command:** make it a step, running that
  command. The command does more than install the package (desktop entries,
  services, defaults). Apps install last, after `mise bootstrap`. Mark one
  `"first": true` only when something carried needs it during `mise bootstrap`
  (a service from its package, a config it would overwrite).
- **Installed by an `omarchy-setup-*` command** (fingerprint, FIDO2, sshd): skip. The
  setup installs it when the person runs it, sometimes as another build (the
  fingerprint setup installs `libfprint-git`, which replaces `libfprint`), so a
  carried copy would fight it. The restore lists the setup for afterwards.
  A carried unit that needs such a package (a unit that restarts `fprintd` after
  sleep) fails until the person runs the setup. Propose a condition line for it,
  `ConditionPathExists=/usr/lib/systemd/system/fprintd.service`, so it skips
  until then. It changes the person's own file, so ask before changing the live
  one to match.
- **Put down by the installer before first boot** (kernel, microcode, sudo): skip.
- **Omarchy's hardware scripts install it** (drivers, firmware): skip. Omarchy installs
  it on hardware that needs it.
- **In the AUR:** carry it as `aur:name`. If it does not build today, see `packages.md`.
- **Removed Omarchy defaults** (`package-removed`): ask. Carry a removal only when it was
  deliberate. It goes into the task as a commented `pacman -Rns` line, because removing
  packages on every bootstrap is risky.
- **Leftovers from experiments** (build tools installed once, packages added today):
  ask, or leave them out. Fewer packages means faster restores.

## Configs

- **Edited from Omarchy's default:** carry it, as a copy and never a symlink. Omarchy's
  migrations and `omarchy refresh` rewrite these files and would break a link.
- **Not shipped, small and text:** read it. Settings get carried. Anything holding a
  host, a token, a session or "last used" values gets skipped.
- **Written by an Omarchy installer** (the reason says so): carry it only if the person
  changed it since. Otherwise the installer step writes it again.
- **App folders with caches or databases:** these are notes. The inspector already
  offers the settings files inside them separately.
- **Per-machine files** (`monitors.lua`): put them in a hardware module.
- **`~/.local/share` is app data, not settings.** Apps, installers and Omarchy write
  what is there, and they write it again on a new machine. The inspector only looks
  at `applications/`, and most desktop entries there have an author:
  - Omarchy ships them (`$OMARCHY_PATH/applications`), and a tool may have rewritten
    their `Exec=` line (omaprofile does). That is a note: the tool does it again.
  - An Omarchy installer wrote them (`omarchy-webapp-install "Name"`, or `Exec=omarchy-launch-*`).
  - The app registered a link handler (`NoDisplay=true` with `x-scheme-handler/`).
  - An installer under `~/.local/share/<app>` wrote them (their icon lives there).

  Carry only entries nothing else writes: a web app or launcher the person made by
  hand. Carry the tool that writes the others instead.
- **Files Omarchy dots tracks** (when `dots_origin` is set): skip them. Dots syncs them
  already, and two tools writing one file will fight.

## System files

- **Changed or added under `/etc`, not by Omarchy:** carry them in `[bootstrap.files]`
  with owner, group and mode.
- **Per-machine files** (`fstab`, `hostname`, users, locale): skip. The installer sets them.
- **Firewall rules:** never carry `/etc/ufw/*.rules`. Ask which rules the person added and
  carry them as `ufw` commands in a step.
- **Power, lid and hardware tweaks** (`logind.conf.d`, RAPL limits, udev rules for one
  device): usually a module.
- **Files only root can read:** the generator prints the `sudo cat` to copy them. Run it
  with the person's go-ahead.

## Services

- **Enabled by the person:** carry them. A oneshot unit gets `state = "stopped"`: it is
  enabled for boot, but not started on every bootstrap.
- **Units pulled in by another unit** (`Also=`), or enabled by Omarchy: skip.
- **User units the person wrote:** carry the unit file in `[bootstrap.files]` (it must
  exist before the services phase) and the service with `scope = "user"`.
- **A service needs its package carried.** The generator warns when it is not.

## Repos

- **Something on the desktop runs from it** (a command link, Hyprland config, a unit,
  a deployed plugin): carry it in `[bootstrap.repos]`.
- **Development checkouts:** skip, even active ones. Cloning every project on every
  machine is slow, and one unreachable private repo stops the whole bootstrap. The README
  can list them for cloning by hand.
- **Unpushed commits or no remote:** a note. Tell the person, since the setup cannot
  bring that work back.
- **A remote that cannot be reached:** if the person still wants it, it goes in the task
  as a clone that is allowed to fail. See `packages.md`.
- **A reference to a repo that looks stale** (an old path in a keybinding): ask. Fix the
  config rather than carrying a dead checkout.

## Plugins and commands

See `plugins.md`. In short:

- A plugin in its own repo goes in `[bootstrap.repos]`.
- A plugin copied from a project's `plugin/` folder is deployed with `rsync` in the task.
- A plain folder gets carried as a copy, but suggest giving it its own repo.
- A link in `~/.local/bin` into a carried repo or plugin is recreated in the task.
- A script the person wrote is carried in `[bootstrap.files]` with mode `0755`.
- A wrapper or binary some installer dropped (it names `~/.something/` or `~/.local/share/`):
  leave it out, and make running that installer a step.

## Logins, keys and personal data

These are always steps, notes or left out, never files: SSH keys, gh,
Tailscale, fingerprints, Wi-Fi, GPG, and credential files. For Tailscale, carry the
`tailscale` package and `tailscaled.service`, not Omarchy's installer, which also
runs `tailscale up`: the Tailscale step lists signing in for after the restore. `~/.ssh/config` can be carried
in a private repo after the person confirms it holds nothing private, with
permissions `0600`.

Personal folders (Documents, Pictures) are notes pointing at a real backup.
