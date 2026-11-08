# shellcheck shell=bash disable=SC2154 # sourced by bootstrap.sh, which sets CHECK, REPO_DIR and friends
# Pick the hardware modules for this machine. Each folder in modules/ with a
# detect script is one module: mise.<name>.toml holds its config, and detect
# exits 0 on hardware it fits. The choice is saved in miserc.local.toml, which
# stays on this machine.
header "Hardware modules"
note "This machine: $(cat /sys/class/dmi/id/sys_vendor 2>/dev/null) $(cat /sys/class/dmi/id/product_name 2>/dev/null)"

if [[ -f $MISERC ]]; then
  ok "Keeping the existing choice: $(grep -m1 '^env' "$MISERC" || echo 'no modules')"
  note "Edit $MISERC to change it."
  return
fi

chosen=()
for detect in "$REPO_DIR"/modules/*/detect; do
  [[ -x $detect ]] || continue
  module=$(basename "$(dirname "$detect")")
  about=$(sed -n 's/^# about: //p' "$detect")
  if "$detect" >/dev/null 2>&1; then
    todo "$module matches this machine${about:+ ($about)}"
    ask "Include the $module module?" && chosen+=("$module")
  else
    todo "$module does not match this machine${about:+ ($about)}"
    ask --default=false "Include the $module module anyway?" && chosen+=("$module")
  fi
done
((CHECK)) && return

env="env = [$(printf '"%s", ' "${chosen[@]}" | sed 's/, $//')]"
((${#chosen[@]})) || env='env = []'
mkdir -p "$(dirname "$MISERC")" && echo "$env" >"$MISERC" && ok "Saved $env to $MISERC"
