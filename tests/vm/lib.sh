# shellcheck shell=bash
# Shared by the VM scripts. Everything that belongs to one machine lives in the
# state folder, outside this repo: the disk images, the VM's ssh key, the disk
# password, and copies of private repos. See docs/validation.md.
VM_DIR=${OMARCHY_VM_DIR:-$HOME/VMs/omarchy-test}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
N=${VM:-1}                                 # VM=2 runs a second instance next to the first
SFX=$([[ $N == 1 ]] || echo "$N")
PORT=$((2221 + N))                         # ssh, on this machine only
export QMP_SOCK=$VM_DIR/qmp$SFX.sock

[[ -d $VM_DIR ]] || { echo "No VM folder at $VM_DIR. See docs/validation.md to set one up." >&2; exit 2; }
# local.env sets VM_PASSWORD (the test VM's disk and sudo password, a VM-only
# one) and optionally MIRROR_GITHUB_USER. It is never committed.
# shellcheck source=/dev/null
[[ -f $VM_DIR/local.env ]] && source "$VM_DIR/local.env"

need_password() {
  [[ -n ${VM_PASSWORD-} ]] || { echo "Set VM_PASSWORD in $VM_DIR/local.env (the test VM's own password)." >&2; exit 2; }
}

# Run a command in the VM over ssh (no command: a shell).
vm() {
  ssh -i "$VM_DIR/vm_key" -p "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=8 -o BatchMode=yes -o LogLevel=ERROR user@localhost "$@"
}

qmp() { python3 "$HERE/qmp.py" "$@"; }

running() { [[ -S $QMP_SOCK ]] && qmp status >/dev/null 2>&1; }

# The VM fetches setup repos and mirrors from $VM_DIR/serve at 10.0.2.2:8765.
serve_up() {
  mkdir -p "$VM_DIR/serve"
  curl -sf -o /dev/null 127.0.0.1:8765/ && return
  (cd "$VM_DIR/serve" && setsid python3 -m http.server 8765 --bind 127.0.0.1 >"$VM_DIR/http.log" 2>&1 &)
  sleep 1
}
