# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Enroll a finger. Enrollment lives in the reader's machine, not in the repo,
# and it waits on the person at the reader, so it is listed for afterwards.
header "Fingerprint"
if ! omarchy-hw-fingerprint 2>/dev/null; then
  ok "No fingerprint reader, nothing to do"
  return
fi
if command -v fprintd-list >/dev/null && fprintd-list "$USER" 2>/dev/null | grep -q ' - #'; then
  ok "A finger is enrolled"
  return
fi
todo "Reader found, no finger enrolled"
later "Enroll a finger: omarchy-setup-security-fingerprint"
