# Omarchy shell plugins

Omarchy's shell finds plugins in `~/.config/omarchy/plugins/*/manifest.json`. How
a plugin got there decides how a new machine should get it.

## One plugin per repo

`omarchy plugin add <git-url>` and `omarchy plugin update` expect a repo with
`manifest.json` at its root, holding exactly one plugin. A plugin that lives in
a subfolder of a bigger project cannot be added or updated that way. For a
plugin worth sharing, suggest giving it its own repo.

## Hot reload

The shell watches the plugin folders with `inotifywait -r`. It ignores `.git`
and does not follow symlinks. So:

- **A plugin checked out as a git repo** reloads when its files change. Good.
- **A symlink to a project folder never reloads.** Deploy a copy instead.
- **A copy deployed with `rsync -ac --delete`** reloads, because rsync writes real files.

## How each kind is carried

| What the inspector found | Deploy | Where it goes |
|---|---|---|
| A checkout of its own repo | `git` | `[bootstrap.repos]` at the plugin's path |
| A copy of a project's `plugin/` folder | `rsync` | the project in `[bootstrap.repos]`, then `rsync -ac --delete` in the task |
| Cloned from a local checkout | `clone` | `[ -d X ] \|\| git clone <checkout> X` in the task, after the checkout's repo |
| A symlink | `link` | replaced by an `rsync` deploy from the link's target |
| A plain folder | `copy` | a directory entry in `[dotfiles]`, and the `sync` task copies edits back |

A plain folder can hold more than the plugin: old copies, snapshots of other
branches, backups. Look before carrying it whole. If its `manifest.json` points
into one subfolder, carry the manifest and that subfolder only, and make the
`sync` task copy back the same subset.

With `rsync` deploys, the project is the source of truth. Edit there, commit
there, then `mise run bootstrap` to deploy. Edits made to the installed copy are
overwritten. Say so in the generated README.

## Commands that ship inside a plugin

If `~/.local/bin` links into a plugin's `bin/` folder, the link is recreated in
the bootstrap task. Repos and plugins exist by then.

## Enabled or not

Which plugins are enabled, and where they sit on the bar, is stored in
`~/.config/omarchy/shell.json`. Carry that file, and the layout comes back with
the plugins.

## Plugins whose source disappeared

If a plugin's remote cannot be reached, the inspector says so. The person may
still want it on machines where it can be cloned. Try the clone in the task, and
let it fail:

```sh
if [ ! -d "$HOME/.config/omarchy/plugins/example.plugin" ]; then
  GIT_TERMINAL_PROMPT=0 git clone --quiet https://github.com/example/plugin.git \
    "$HOME/.config/omarchy/plugins/example.plugin" 2>/dev/null ||
    echo "example/plugin is unavailable, skipped"
fi
```

Do not mirror or re-host someone else's plugin without asking the person.
Licenses and the author's wishes matter more than convenience.
