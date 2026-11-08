# inventory.json

`bin/inspect` writes one JSON file describing what on this machine differs
from stock Omarchy.

```json
{
  "schema": 1,
  "generated": "2026-11-07T22:33:14+01:00",
  "omarchy": { "version": "4.0.6-1", "path": "/usr/share/omarchy" },
  "mise": "2026.10.25",
  "user": "me", "home": "/home/me",
  "dots_origin": "",
  "machine": { "vendor": "Framework", "product": "Laptop 13 Pro (...)", "cpu": "intel", "...": "..." },
  "counts": { "carry": 83, "review": 75, "...": 0 },
  "items": [ ... ]
}
```

`dots_origin` is set when Omarchy dots (mise's dotfile history) syncs through an
origin repo. Files it tracks should be left to it.

## Items

```json
{
  "id": "package:keyd",
  "kind": "package",
  "name": "keyd",
  "class": "carry",
  "module": null,
  "reason": "Installed by you, not part of Omarchy.",
  "facts": { "source": "pacman", "version": "2.6.0-5", "description": "..." }
}
```

`id` is `kind:name` and is what decisions refer to. `class` is one of `carry`,
`module`, `step`, `note`, `skip` and `review` (see `AGENTS.md`). `module` is set
when the class is `module`.

## Kinds and their facts

| Kind | From | Facts |
|---|---|---|
| `package` | packages | `source` (pacman or aur), `version`, `description`, `installer` |
| `package-removed` | packages | none: an Omarchy default that is not installed |
| `config` | configs, tools | `path`, `size`, `mode`, `text`, `default`, `lines_changed` |
| `config-dir` | configs | `path`, `files`, `kb`, `sample`: an app folder judged as a whole |
| `desktop-entry` | configs | `path`, `title` |
| `theme` | configs | git facts: an Omarchy theme from its own repo |
| `system-file` | system | `path`, `source` (modified or unowned), `package`, `owner`, `group`, `mode`, `readable` |
| `masked-unit` | system | `path` |
| `service` | services | `scope`, `unit`, `unit_file`, `unit_from`, `active`, `package` |
| `user-unit` | services | `path`: a unit file in `~/.config/systemd/user` |
| `repo` | repos | git facts and `used_by`: what on the desktop points into it |
| `plugin` | plugins | `id`, `path`, `enabled`, `deploy` (git, rsync, clone, copy, link), `source` |
| `link` | commands | `path`, `target` |
| `command` | commands | `path`, `mode`, `header`, `wraps` |
| `tool` | tools | `manager`, `mise`: the mise backend that would carry it |
| `identity` | identity | names and counts only, never contents |
| `credential`, `personal-data` | identity | `path`, `kb` |

Git facts are `path`, `url`, `branch`, `dirty` (uncommitted files), `ahead`
(unpushed commits) and `reachable` (whether `git ls-remote` worked, or null when
offline or local).

## decisions.json

```json
{
  "schema": 1,
  "inventory": "<the inventory's generated timestamp>",
  "decisions": {
    "<item id>": { "class": "module", "module": "framework", "why": "...", "by": "you" }
  }
}
```

`"first": true` on an app installed by an Omarchy installer runs it before
`mise bootstrap` instead of at the end. The agent writes `why`. The blueprint page sets `"by": "you"` on choices the
person made. `bin/generate` applies decisions over the inspector's classes.

## Adding a collector

A collector is a module in `omarchy_blueprint/collectors/` with a
`collect(env)` function that returns items made with
`item(kind, name, cls, reason, facts)`. It must only read.

- Ask the `Env` for everything: `env.run(...)` for commands, `env.home`, `env.etc`
  and `env.omarchy` for paths, `env.corpus` for what Omarchy's own files mention.
  That keeps it testable.
- Add it to `COLLECTORS` in `omarchy_blueprint/collect.py`.
- Document its kind in the table above.
- Teach `omarchy_blueprint/generate.py` where the kind lands.
- Add a test in `tests/` that builds the case with `tests/fake.py`.

`bin/inspect --only NAME` runs one collector and prints its items, which is the
quickest way to work on a rule.
