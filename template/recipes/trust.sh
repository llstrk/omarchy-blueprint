# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# mise only reads config from directories you trust.
header "Trusting this repo"
if trusted; then
  ok "mise trusts $REPO_DIR"
else
  todo "mise does not trust $REPO_DIR yet, so it will not read its config"
  ask "Trust it?" && (cd "$REPO_DIR" && attempt mise trust) && ok "Trusted"
fi
