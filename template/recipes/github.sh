# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Sign in to GitHub. Private repos cannot clone without it, so it comes early.
header "GitHub"
if ! command -v gh >/dev/null; then
  todo "gh is not installed (Omarchy does not ship it)"
  if ask "Install gh with mise?"; then
    attempt mise use -g gh && mise reshim || return
  else
    ((CHECK)) || warn "Skipped. Private repos cannot be cloned without it."
    return
  fi
fi

# Ask for the stored token rather than `gh auth status`: status also fails for
# reasons that do not stop Git from cloning, and then login offers to sign in again.
if gh auth token --hostname github.com >/dev/null 2>&1; then
  ok "Signed in as $(gh api user -q .login 2>/dev/null || echo 'your account')"
else
  todo "Not signed in to GitHub"
  if ask "Sign in to GitHub now?"; then
    attempt gh auth login || return
  else
    ((CHECK)) || warn "Skipped. Private repos cannot be cloned until you sign in."
    ((CHECK)) || later "Sign in to GitHub (gh auth login), then run ./bootstrap.sh again for the private repos"
    return
  fi
fi

if git config --get-all credential.https://github.com.helper 2>/dev/null | grep -q 'gh auth git-credential'; then
  ok "Git uses gh for GitHub logins"
else
  todo "Git does not use gh for GitHub logins yet"
  ask "Set that up (gh auth setup-git)?" && attempt gh auth setup-git && ok "Done"
fi
