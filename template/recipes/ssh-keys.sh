# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# An SSH key for this machine. Keys are never carried in the repo.
header "SSH key"
for key in "$HOME"/.ssh/id_*.pub; do
  [[ -f $key ]] && { ok "Found ${key/#$HOME/\~}"; return; }
done
todo "No SSH key"
note "Skip this if you will restore your existing key from a backup instead."
ask "Create a new ed25519 key?" || {
  ((CHECK)) || later "Restore your SSH key from a backup, or create one: ./bootstrap.sh --only ssh-keys"
  return
}
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
# Asked before mise bootstrap, so the carried git config may not be in place yet.
email=$(git config -f "$REPO_DIR/home/.config/git/config" user.email 2>/dev/null ||
  git config -f "$REPO_DIR/home/.gitconfig" user.email 2>/dev/null ||
  git config user.email || echo "$USER@$(hostname)")
attempt ssh-keygen -t ed25519 -C "$email" -f "$HOME/.ssh/id_ed25519" || return
ok "Created. Add this public key wherever this machine needs access:"
sed 's/^/    /' "$HOME/.ssh/id_ed25519.pub"
