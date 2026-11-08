# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Show what mise bootstrap would change, then apply it.
header "Packages, system files, services, repos and configs"
if ! trusted; then
  todo "Waiting on the trust step: mise will not read an untrusted repo"
  return
fi

plan=$(mise bootstrap plan 2>&1) || {
  echo "$plan" | tail -20
  fail "mise bootstrap plan failed."
}
summary=$(grep -m1 '^Plan:' <<<"$plan")
dry=$(mise bootstrap --dry-run 2>&1)
pending=$(grep -E '^(cp |yay |sudo |pacman |git clone|systemctl)' <<<"$dry")

if [[ $summary == "Plan: 0 create, 0 update,"* && -z $pending ]]; then
  ok "Already in place (${summary#Plan: })"
  if ask "Run the bootstrap task again anyway (mise run bootstrap)?"; then
    attempt mise run bootstrap && ok "Done"
  fi
  return
fi

todo "${summary:-Plan: unknown}"
grep -E '^(create|update|remove) ' <<<"$plan" | awk '{print "      " $1 " " $2}'
[[ -n $pending ]] && while read -r line; do echo "      $line"; done <<<"$pending"
((CHECK)) && return

echo
note "Configs listed with cp replace what is on this machine now."
note "The first run takes a while. After the password it runs on its own until the apps."
ask "Apply all of this now?" || {
  warn "Skipped. Nothing was changed."
  return
}
need_sudo || fail "sudo did not accept the password."

# bootstrap.sh records the whole run in $RESTORE_LOG. Note where mise's part
# starts, to read just that part back if something fails. mise runs in this
# terminal, so sudo already has the password. --yes skips mise's own "apply?"
# prompts, answered above. Without --force-dotfiles, mise stops to ask about
# every config that differs.
log=$RESTORE_LOG
from=$(($(stat -c %s "$log" 2>/dev/null || echo 0) + 1))
mise bootstrap --yes --force-dotfiles
rc=$?
sleep 0.5 # let script(1) write the last lines
# The log is a terminal recording: drop colours and carriage returns to read it.
plain() { tail -c +"$from" "$1" | sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b\][^\x1b]*\x1b\\//g; s/\r//g'; }
# Which packages are still missing says what failed, whatever mise's error
# text is in this version. None missing: the failure came after the packages.
left() { jq -r --arg m "$1" '(.[$m].packages // [])[] | select(.state != "installed") | .package' <<<"$status"; }
status=""
((rc != 0)) && status=$(mise bootstrap packages status --json 2>/dev/null)
if ((rc != 0)) && [[ -n "$(left pacman)$(left aur)" ]]; then
  # mise stops at the first failure, and packages come first. Install what can
  # be installed, then apply everything after the packages instead of nothing.
  warn "A package did not install (mise bootstrap exit $rc). Installing the rest without it."
  plain "$log" | grep -aE 'No AUR package found|^( *-> )?[a-z0-9@._+-]+ - exit status|^error: |[^>] ERROR: ' |
    sed 's/^ *-> //; s/^/      /' | sort -u | head -12
  if [[ -n "$(left pacman)" ]]; then
    # pacman takes the list all or nothing: one name that is gone (renamed, or
    # dropped from the repos) and none install, and mise never gets to the AUR
    # ones. When only AUR ones are missing, yay already built what it could.
    repo=() aur=() gone=()
    for pkg in $(left pacman); do
      if pacman -Si "$pkg" >/dev/null 2>&1; then repo+=("$pkg"); else gone+=("$pkg"); fi
    done
    for pkg in $(left aur); do
      if yay -Si "$pkg" >/dev/null 2>&1; then aur+=("$pkg"); else gone+=("$pkg"); fi
    done
    ((${#repo[@]})) && sudo pacman -S --needed --noconfirm "${repo[@]}"
    ((${#aur[@]})) && yay -S --needed --noconfirm "${aur[@]}"
    for pkg in "${gone[@]}"; do
      warn "$pkg is in neither the Arch repos nor the AUR any more."
      later "$pkg is gone from the Arch repos and the AUR: find what replaced it, then change or remove it in mise.toml"
    done
    sleep 0.5
  fi
  broken=$(plain "$log" | sed -nE 's/^( *-> )?([a-z0-9@._+-]+) - exit status.*/\2/p' | sort -u)
  mise bootstrap --yes --force-dotfiles --skip packages
  rc=$?
  ((rc == 0)) || fail "mise bootstrap failed again (exit $rc). Full output: $log"
  warn "Applied everything else. Fix the package (see $log), then run this again."
  # An AUR package that built on the old machine and fails here has usually
  # been left behind by a dependency Arch updated. Point at the way out.
  for pkg in $broken; do
    note "$pkg did not build from the AUR. Comments there often have the fix:"
    note "  https://aur.archlinux.org/packages/$pkg"
    note "  To pin a build that works, see \"A package that no longer builds\" in README.md."
    later "$pkg did not build: see \"A package that no longer builds\" in README.md"
  done
  return
fi
if ((rc != 0)); then
  # Usually the task, which runs last: everything before it is in place.
  plain "$log" | grep -aE '^ERROR|error:|^mise ERROR' | tail -8 | sed 's/^/      /'
  fail "mise bootstrap failed (exit $rc). Full output: $log"
fi

summary=$(mise bootstrap plan 2>&1 | grep -m1 '^Plan:')
if [[ $summary == "Plan: 0 create, 0 update,"* ]]; then
  ok "Applied and settled (${summary#Plan: }). Log: $log"
else
  warn "Applied, but not everything settled: ${summary:-no plan output}. Log: $log"
fi
