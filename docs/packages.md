# Packages, installers and things that break

## Where Omarchy's packages come from

The inspector treats a package as Omarchy's when it is in any of these:

- `install/omarchy-base.packages`: what the ISO installs. `omarchy-other.packages` only
  lists what the offline mirror must hold, so its packages are not expected everywhere.
- An `omarchy-pkg-add` line in `install/`: hardware scripts add drivers and firmware.
- The first two hours of `/var/log/pacman.log`: the installer before first boot.

Everything else that `pacman -Qqe` lists is the person's.

## Prefer Omarchy's installer

When an `omarchy-install-*` command installs a package, run the command rather
than carrying the package. It also writes desktop entries, enables services and
sets defaults. The generated `steps/80-apps.sh` checks each package and runs the
command for any that are missing, without asking: picking "Install everywhere"
in the blueprint was the decision.

It runs last. The base system (packages, files, services, configs, repos) gets
set up first, without app questions and windows in between, and an app that
fails is easy to install by hand later. An app that something carried needs
during `mise bootstrap` (a service from its package, a config its installer
would overwrite) is marked `"first": true` in the decisions and installs from
`steps/35-omarchy-installers-first.sh`, before it.

Within the step, installers that ask a question (T3 Code's channel, Voxtype's
model download) run first, and the step says when no more questions are coming.
The rest runs unattended; Hermes is the slow one, since it downloads a large repo.
They cannot run side by side: most install through pacman, which allows one at a
time ("unable to lock database"), and the questions and sudo prompts would share
one popup.

What a fresh install taught the step (Omarchy 4.0 to 4.5):

- **Installers get renamed.** The new machine usually runs a newer Omarchy, and
  `omarchy-voxtype-install` had become `omarchy-install-dictation-voxtype`. When
  the saved name is gone, the step uses whichever `omarchy-install-*` adds the package.
- **Some installers only act when told to.** `omarchy-install-hermes-cli` and
  `omarchy-install-openclaw-cli` print their usage unless given `--now`. The step
  passes `--now` when the installer's `# omarchy:args=` line offers it.
- **Some installers stop using the package.** T3 Code became a download that
  updates itself, so `t3code-bin` never shows as installed. The step remembers an
  installer that finished and does not run it again.
- **Some installers sign in.** `omarchy-install-service-tailscale` runs
  `tailscale up`, which would stop the restore to wait on a browser. The
  inspector leaves such installers out and carries the package; carry
  `tailscaled.service` with it. The Tailscale step lists signing in for afterwards.
- **Some installers ask.** T3 Code asks for a channel and Voxtype asks before
  downloading its model, in the bootstrap popup.
- **Some installers open their app.** ChatGPT, Spotify and T3 Code start the app
  when they finish, and its window takes the keyboard from the bootstrap popup, so
  the next question cannot be answered. The step gives the keyboard back to the
  popup when a new window opens. It does not pass T3 Code's `--no-launch`: the
  app creates its `t3` command on first launch, and without it `~/.local/bin/t3`
  is a broken link until the person opens the app.

The restore keeps Omarchy's stay-awake toggle on while it runs (the cup in the
bar), and turns it off again at the end unless it was already on. Without it, the
screensaver started during the installers, apps opened onto the screensaver's
workspace, and the screen locked while a question was waiting.

## An AUR package that no longer builds

AUR packages break when their dependencies move on. One example: wl-kbptr 0.4.1
asked meson for `opencv4` after Arch moved to OpenCV 5, which only ships
`opencv5.pc`. The build failed with "exit status 4". mise stops at the first
failure, so the bootstrap step now applies everything after packages anyway
(`--skip packages`), lists what failed and asks for a rerun once it is fixed.

The fix that worked:

1. Find the upstream commit that fixes it, and pin a PKGBUILD to it in
   `pkgbuilds/<name>/PKGBUILD`, with the commit and checksum, based on the AUR one.
2. Drop `aur:<name>` from `[bootstrap.packages]`.
3. Build it in the task, last, so a failure is reported but everything else is done:

   ```sh
   if ! pacman -Q wl-kbptr >/dev/null 2>&1; then
     build=$(mktemp -d)
     cp pkgbuilds/wl-kbptr/PKGBUILD "$build/"
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

4. Say in the PKGBUILD how to undo it once the AUR package works again.
5. Add `options=('!debug')`, or makepkg also installs a `-debug` package next to it.

A foreign package that is not in the AUR at all (built from a local checkout, or
from a repo that is gone) cannot be installed by name. The inspector checks the
AUR and makes those notes. Carry the source repo and build it, or leave it out.

Find these before a restore does: `bin/check-builds REPO` builds every `aur:`
package and every `pkgbuilds/` entry in throwaway folders, without installing,
and names the ones that fail with their errors. It runs the build scripts, so
use a spare machine or VM, or ask first. The inspector also says when an AUR
package is flagged out of date, a common sign that it no longer builds.

During a restore, `bootstrap.sh` names a package that failed to build, links its
AUR page and points at the README section that repeats the steps above.

## Something you want, but may not be able to get

When the inspector reports a remote that cannot be reached, the person may still
want it where it works. Do not put it in `[bootstrap.repos]`, since one failed clone
fails the phase. Clone it in the task with `GIT_TERMINAL_PROMPT=0` (so a vanished
private repo does not stop to ask for a password), and `|| echo ... skipped`.

## Tools outside mise

Global npm, cargo, uv, pipx and bun installs are not recorded anywhere a new
machine can read. The inspector lists them with the mise backend that carries
them (`npm:name`, `cargo:name`, `pipx:name`). If the person wants them, the task
runs `mise use -g <backend:name>` for each. Better still, add them to
`~/.config/mise/config.toml` and let the tools phase install them.

## gh

Omarchy does not ship `gh`. Private repos need it before bootstrap clones them,
so the github step installs it with `mise use -g gh`, signs in, and runs
`gh auth setup-git`. Check sign-in with `gh auth token --hostname github.com`, not
`gh auth status`. Status fails for reasons that do not stop git, and then the
step offers a login the person already has.

If the carried `~/.config/git/config` has a credential helper pointing at a
versioned gh path (`/home/me/.local/share/mise/installs/gh/2.98.0/bin/gh`),
replace it with `!gh auth git-credential`, which survives gh updates.
