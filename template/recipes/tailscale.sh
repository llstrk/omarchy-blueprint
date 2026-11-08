# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Join the tailnet as a new device. Logging in waits on a browser, so the
# restore does not do it: it lists the command for afterwards.
header "Tailscale"
command -v tailscale >/dev/null || { warn "tailscale is not installed. The bootstrap step should have installed it."; return; }
state=$(tailscale status --json 2>/dev/null | jq -r '.BackendState // empty')
if [[ $state == Running ]]; then
  ok "Connected as $(tailscale status --json 2>/dev/null | jq -r '.Self.HostName')"
  return
fi
todo "Not connected (${state:-tailscaled not answering})"
note "Join as a new device. Never copy /var/lib/tailscale from another machine."
later "Join your tailnet: sudo tailscale up"
