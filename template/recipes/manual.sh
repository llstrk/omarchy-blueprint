# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Steps this script cannot do for you. Each one is shown until you mark it done.
# Each line: an id, then what to do.
MANUAL=(
  #MANUAL#
)

header "By hand"
for entry in "${MANUAL[@]}"; do
  read -r id text <<<"$entry"
  if done_marker "manual-$id"; then
    ok "$text"
    continue
  fi
  todo "$text"
  ask --default=false "Done?" && mark_done "manual-$id"
done
