# Restoring on a new machine

1. **Install Omarchy** from the ISO. Log in once so first-run setup finishes, then run
   `omarchy update`. The setup's `min_version` needs a recent mise.
2. **Sign in to GitHub and fetch the setup repo.** If the repo is private, gh comes
   first, from mise:

   ```sh
   mise use -g gh
   mise x -- gh auth login
   mise x -- gh auth setup-git
   git clone https://github.com/<you>/<setup>.git ~/Work/<setup>
   ```

3. **Run the guided restore:** `~/Work/<setup>/bootstrap.sh`. It opens in an Omarchy
   popup and walks through the steps. The questions come first, so the long part
   runs on its own:
   - hardware modules, offered when `modules/<name>/detect` matches
   - an SSH key, if there is none
   - trusting the repo
   - `mise bootstrap`, after showing the plan and the configs it will replace,
     then your password, once for the whole run
   - then packages, system files, services, repos and configs install unattended
   - last, the apps you chose to install with Omarchy's installers. Those that ask
     a question of their own go first; the rest (Hermes is slow) runs unattended.
   - at the end, a list of what is left for you: joining Tailscale, enrolling a
     finger, anything that did not install. Nothing in the run waits on a login
     or a reader, except GitHub at the start.
4. **Log out and back in.**

Rehearse first with `./bootstrap.sh --check`, which reports what each step
would do and changes nothing. `--only <step>` reruns one step. Logs are in
`~/.local/state/<setup>/`.

Testing on a spare machine before you rely on it is worth the hour. The
source machine can only prove that the repo matches it, not that it restores
cleanly from nothing.
