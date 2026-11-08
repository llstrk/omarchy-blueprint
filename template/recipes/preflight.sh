# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Check that this is an Omarchy machine with what the other steps need.
header "Checking this machine"
command -v omarchy >/dev/null || fail "This does not look like an Omarchy install."
command -v gum >/dev/null || fail "gum is missing. It ships with Omarchy, so update Omarchy first."
[[ -f $REPO_DIR/mise.toml ]] || fail "No mise.toml next to this script in $REPO_DIR."
curl -fsS --max-time 10 -o /dev/null https://github.com || fail "Cannot reach github.com. Connect to the internet and try again."

have=$(mise --version 2>/dev/null | awk '{print $1}')
need=$(sed -n 's/^min_version = "\(.*\)"/\1/p' "$REPO_DIR/mise.toml")
if [[ -z $have ]]; then
  fail "mise is missing. It ships with Omarchy, so update Omarchy first."
elif [[ -n $need && $(printf '%s\n' "$need" "$have" | sort -V | head -1) != "$need" ]]; then
  fail "mise $have is older than $need. Run omarchy update, then start this again."
fi
ok "Omarchy, mise $have and a connection to GitHub"
