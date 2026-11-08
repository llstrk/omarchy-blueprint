# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Apps Omarchy installs with its own commands. Running the command does the
# extra setup the package alone does not (desktop entries, services, logins).
# Each line: package to check, then the command that installed it on the old machine.
INSTALLERS=(
  #INSTALLERS#
)

# Omarchy's installers expect what its session sets; this may run outside one.
export OMARCHY_PATH=${OMARCHY_PATH:-/usr/share/omarchy}

# Installers get renamed between Omarchy versions, and the new machine usually
# has a newer one. When the old name is gone, use whichever installer on this
# machine adds the package.
installer_for() {
  local pkg=$1 cmd=$2 c
  command -v "$cmd" >/dev/null && { echo "$cmd"; return; }
  for c in $(compgen -c omarchy-install- | sort -u); do
    grep -qE "omarchy-pkg-(aur-)?add( [^#]*)? $pkg( |\$)" "$(command -v "$c")" 2>/dev/null && { echo "$c"; return; }
  done
}

#TITLE#
# They cannot run side by side: most install through pacman, which takes one
# at a time, and some ask a question. Those that ask go first, so the person
# can walk away while the rest (Hermes takes a while) finishes on its own.
done=() asks=() quiet=()
for entry in "${INSTALLERS[@]}"; do
  read -r pkg cmd <<<"$entry"
  run=$(installer_for "$pkg" "$cmd")
  if pacman -Q "$pkg" >/dev/null 2>&1 || done_marker "installer-$pkg"; then
    done+=("$entry")
  elif [[ -n $run ]] && grep -qE 'gum (confirm|choose|input)' "$(command -v "$run")"; then
    asks+=("$entry")
  else
    quiet+=("$entry")
  fi
done
for entry in "${done[@]}" "${asks[@]}" "${quiet[@]}"; do
  if ((!CHECK && ${#asks[@]} && ${#quiet[@]})) && [[ $entry == "${quiet[0]}" ]]; then
    note "No more questions from here: the rest installs on its own."
  fi
  read -r pkg cmd <<<"$entry"
  # Some installers stop using the package (an app that updates itself), so
  # an installer that finished once counts as done too.
  if pacman -Q "$pkg" >/dev/null 2>&1; then
    ok "$pkg is installed"
    continue
  elif done_marker "installer-$pkg"; then
    ok "$pkg: its Omarchy installer finished on an earlier run"
    continue
  fi
  run=$(installer_for "$pkg" "$cmd")
  if [[ -z $run ]]; then
    warn "No Omarchy installer for $pkg here ($cmd is gone). Install it some other way."
    continue
  fi
  # Some installers only act when told to: their usage line offers --now.
  args=()
  grep -q '^# omarchy:args=.*--now' "$(command -v "$run")" && args=(--now)
  line="$run${args[*]:+ ${args[*]}}"
  if ((CHECK)); then
    todo "$pkg is not installed: $line will install it"
  else
    # You chose this in the blueprint, so run it without asking again.
    need_sudo || fail "sudo did not accept the password."
    echo "  → Installing $pkg with $line"
    # Several open their app when done (T3 Code only finishes setting up on that
    # first launch), so let them, then take the keyboard back.
    open=$(windows)
    if attempt "$run" "${args[@]}"; then
      mark_done "installer-$pkg"
    else
      later "$pkg did not install: run ./bootstrap.sh again, or $line"
    fi
    focus_back "$open"
  fi
done
