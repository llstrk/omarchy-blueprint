# When a restore fails

These are the failures seen when restoring generated setups on real machines.

## "sudo requires a password but no TTY is available"

mise ran without a terminal, usually because its output was piped through `tee`.
Log with `script(1)` instead, which keeps a terminal. The generated `bootstrap.sh`
runs the whole restore under one `script` session and logs it to
`~/.local/state/<repo>/restore-*.log`.

## sudo asks for the password again and again

sudo remembers the password per terminal for 10 minutes (Omarchy's
`timestamp_timeout`), so three things make it ask again:

- **A new terminal.** Every `script -c` starts one. Wrap the whole run once, not
  each command.
- **Time.** A long package install outlasts 10 minutes. `bootstrap.sh` refreshes
  sudo in the background (`sudo -n -v` every minute) once the password is given.
- **makepkg.** It calls `sudo -k pacman`, which ignores the remembered password,
  so one build asks up to three times (dependencies, install, cleanup). Give it a
  config with `PACMAN_AUTH=(sudo)`, as the pin recipe in `packages.md` does.
  yay and Omarchy's installers use plain sudo.

## gh asks to sign in, then says you are already signed in

The step checked `gh auth status`, which can fail for reasons unrelated to git
(a second host, a scope warning). Check `gh auth token --hostname github.com`
instead. The generated github step does.

## A clone fails and the whole repos phase stops

One repo in `[bootstrap.repos]` cannot be cloned: it is private and gh is not set
up, it was deleted, or the account is gone. Either:

- run the github step first (`./bootstrap.sh --only github`), or
- move the repo out of `[bootstrap.repos]` into the task as a clone allowed to fail
  (see `packages.md`).

## An AUR package fails to build ("exit status 4" or similar)

The bootstrap step applies everything else and lists the package. Check the
build log in `~/.local/state/<repo>/restore-*.log`. If a dependency moved on,
build a pinned PKGBUILD in the task (see `packages.md`), then run `bootstrap.sh` again.

## "No AUR package found for ..."

The package was built here, not installed from the AUR. Carry its source repo
and build it in the task, or leave it out.

## mise asks about every config file

mise runs in a terminal and found configs that differ. The bootstrap step passes
`--force-dotfiles` after listing them. By hand:
`mise bootstrap --force-dotfiles`.

## "Config files in ... are not trusted"

Run `mise trust` in the repo. The trust step does this.

## A service fails to start or is "unknown"

Its unit does not exist on the new machine. Carry the package that ships it, or,
for a user unit, carry the unit file in `[bootstrap.files]`.

## A plugin does not reload after edits

It is a symlink. Deploy a copy with `rsync` (see `plugins.md`).

## The plan is not empty on the source machine

A carried copy differs from the live file, so it changed since generation. Run
`mise run sync` to copy live edits back, or regenerate. If a path is wrong, fix
it in `mise.toml`.

## Bootstrapped, but things look old

Log out and back in. Hyprland, keyd and the shell only pick up some changes
after a new session. New udev rules need a reboot or
`sudo udevadm control --reload`.
