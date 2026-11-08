#!/usr/bin/env bash
# Walk an Omarchy install through restoring this setup, one step at a time.
# Every step checks whether it is already done, so it is safe to run again.
#
#   ./bootstrap.sh              open in an Omarchy popup
#   ./bootstrap.sh --no-popup   run in this terminal
#   ./bootstrap.sh --check      report what each step would do, change nothing
#   ./bootstrap.sh --only NAME  run one step (the part of its file name after the number)
#
# The steps are the files in steps/, run in name order. Add, remove or reorder
# them freely: each one is a short script using the helpers in lib/ui.sh.
#
# Not to be confused with `mise run bootstrap`, the task in mise.toml that
# `mise bootstrap` runs at the end. The bootstrap step calls `mise bootstrap`.

set -uo pipefail

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
NAME=${REPO_DIR##*/}
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/$NAME"
MISERC="$HOME/.config/mise/miserc.local.toml"
CHECK=0
POPUP=1
ONLY=""

usage() { sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

args=("$@")
while (($#)); do
  case $1 in
    --check) CHECK=1 ;;
    --no-popup) POPUP=0 ;;
    --only) ONLY=${2:-}; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "bootstrap.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# Reopen in Omarchy's floating terminal, unless we are already in one.
if ((POPUP)) && [[ -n ${WAYLAND_DISPLAY-} ]] && command -v omarchy-launch-floating-terminal-with-presentation >/dev/null; then
  exec omarchy-launch-floating-terminal-with-presentation "$(printf '%q ' "$REPO_DIR/bootstrap.sh" --no-popup "${args[@]}")"
fi

# Record the whole run in one terminal. sudo remembers the password per
# terminal, so everything that runs in this one (mise, pacman, the installers)
# shares one password prompt. script(1) also keeps the log for troubleshooting.
if ((!CHECK)) && [[ -z ${RESTORE_LOG-} ]]; then
  mkdir -p "$STATE_DIR"
  RESTORE_LOG="$STATE_DIR/restore-$(date +%Y%m%d-%H%M%S).log"
  export RESTORE_LOG
  # script(1) runs the command with $SHELL, and the line below is bash.
  SHELL=/bin/bash exec script -q -e -f -c "$(printf '%q ' "$REPO_DIR/bootstrap.sh" "${args[@]}")" "$RESTORE_LOG"
fi

# The popup is a non-interactive shell, so mise has not put its tools on PATH.
# gh has to be there: Git asks it for GitHub credentials while repos clone.
export PATH="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}/shims:$PATH"
export REPO_DIR NAME STATE_DIR MISERC CHECK

source "$REPO_DIR/lib/ui.sh"

# Commands to run when the restore ends, however it ends.
cleanup=()
on_exit() { local c; for c in "${cleanup[@]}"; do eval "$c"; done; }
trap on_exit EXIT

# A restore runs long stretches with nobody typing, and Omarchy's screensaver and
# lock would cover the questions. Stay awake until the run ends, unless the
# person had already turned that on.
if ((!CHECK)) && command -v omarchy-toggle-idle >/dev/null &&
  [[ $(omarchy-toggle-idle status 2>/dev/null) == *'"enabled":false'* ]]; then
  omarchy-toggle-idle stay-awake >/dev/null && cleanup+=('omarchy-toggle-idle allow-idle >/dev/null')
fi

# Once the password has been given (need_sudo), keep sudo from forgetting it
# while long installs run, so it is asked for once.
if ((!CHECK)); then
  (while kill -0 $$ 2>/dev/null; do sudo -n -v 2>/dev/null; sleep 60; done) &
  cleanup+=("kill $! 2>/dev/null")
fi

# What steps leave for the person (later in lib/ui.sh), listed at the end.
LATER_FILE=$(mktemp "${TMPDIR:-/tmp}/restore-later.XXXXXX")
export LATER_FILE
cleanup+=("rm -f '$LATER_FILE'")

gum style --bold --border rounded --padding "0 2" --margin "1 0" \
  "$NAME" "$( ((CHECK)) && echo 'Check only: nothing will change' || echo "from $REPO_DIR")"

for step in "$REPO_DIR"/steps/*.sh; do
  name=${step##*/}
  name=${name%.sh}
  name=${name#[0-9][0-9]-}
  [[ -n $ONLY && $name != "$ONLY" ]] && continue
  # Each step runs in a subshell, so `return` ends the step and `fail` ends the run.
  # shellcheck source=/dev/null
  (cd "$REPO_DIR" && source "$step")
  rc=$?
  if ((rc == FAIL_EXIT)); then
    exit 1
  fi
done

header "Finished"
if [[ -s $LATER_FILE ]]; then
  note "$( ((CHECK)) && echo 'A normal run would leave these for you:' || echo 'Left for you, whenever suits:')"
  while read -r line; do todo "$line"; done <"$LATER_FILE"
  echo
fi
if ((CHECK)); then
  note "Nothing was changed. Items marked • are what a normal run would offer."
else
  note "Log out and back in so Hyprland, services and shell plugins pick everything up."
  note "Run this again any time: finished steps are skipped."
fi
