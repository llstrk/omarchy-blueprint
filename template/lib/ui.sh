# shellcheck shell=bash
# Helpers for the steps in steps/. Sourced by bootstrap.sh.
#
#   header TEXT      start a step
#   ok TEXT          already done, or just done
#   todo TEXT        something this step would change
#   note TEXT        an indented detail
#   warn TEXT        something went wrong, but the run continues
#   fail TEXT        stop the whole run
#   ask PROMPT       gum confirm, and always "no" in --check mode
#   attempt CMD...   run CMD, warn instead of stopping when it fails
#   done_marker ID   true once mark_done ID has run on this machine
#   need_sudo        ask for the password now, once for the whole run
#   later TEXT       something left for the person, listed when the run ends
#   windows          the Hyprland windows open now, to pass to focus_back
#   focus_back LIST  when a window not in LIST opens, give the keyboard back to this one

FAIL_EXIT=3

header() { echo; gum style --bold --foreground 4 "$*"; }
ok() { echo "  ✓ $*"; }
todo() { echo "  • $*"; }
note() { echo "    $*"; }
warn() { gum style --foreground 3 "  ! $*"; }

fail() {
  echo
  gum style --bold --foreground 1 "✗ $*"
  exit "$FAIL_EXIT"
}

# Ask before acting. In --check mode nothing is ever acted on.
ask() {
  ((CHECK)) && return 1
  gum confirm "$@"
}

# Run a command, and keep going if it fails: later steps may still help.
attempt() {
  "$@" && return 0
  warn "That did not finish (exit $?). You can rerun this script to try again."
  return 1
}

# The restore never stops to wait on the person mid-run (a login, a finger on
# the reader). Steps hand those over with later, and the end lists them.
later() {
  echo "$*" >>"$LATER_FILE"
  note "Left for after the run: listed at the end."
}

# Everything after this runs as the person waits, so ask for the password at a
# moment they are there. bootstrap.sh keeps it fresh from then on.
need_sudo() {
  ((CHECK)) && return 0
  sudo -n true 2>/dev/null && return 0
  note "Your password, once for this whole run: packages and system files need it."
  sudo -v
}

done_marker() { [[ -f $STATE_DIR/$1.done ]]; }
mark_done() { mkdir -p "$STATE_DIR" && touch "$STATE_DIR/$1.done"; }

# True when mise trusts this repo, so it will read its config.
trusted() { (cd "$REPO_DIR" && mise trust --show 2>/dev/null | grep -q ': trusted$'); }

windows() { hyprctl clients -j 2>/dev/null | jq -r '.[].address' | sort; }

# Some of Omarchy's installers open their app when they finish, and the new
# window takes the keyboard from this one. Wait a little for it, then take the
# keyboard back so the next question can be answered.
focus_back() {
  local before=$1 pid=$$ pids=" " self _
  [[ -n ${HYPRLAND_INSTANCE_SIGNATURE-} ]] && command -v jq >/dev/null || return 0
  for _ in {1..10}; do
    [[ -n $(comm -13 <(echo "$before") <(windows)) ]] && break
    sleep 1
  done
  [[ -n $(comm -13 <(echo "$before") <(windows)) ]] || return 0
  sleep 1
  # This window is the one whose process started this script.
  while ((pid > 1)); do
    pids+="$pid "
    pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
  done
  self=$(hyprctl clients -j | jq -r --arg p "$pids" 'first(.[] | select(.pid as $x | $p | contains(" \($x) "))) | .address')
  [[ -n $self ]] || return 0
  hyprctl dispatch "hl.dsp.focus({ window = \"address:$self\" })" >/dev/null 2>&1 ||
    hyprctl dispatch focuswindow "address:$self" >/dev/null 2>&1
  return 0
}
