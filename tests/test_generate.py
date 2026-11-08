"""What the generator writes for each kind of decision."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from omarchy_blueprint import generate


def it(kind, name, cls="carry", module=None, **facts):
    return {"id": f"{kind}:{name}", "kind": kind, "name": name, "class": cls, "module": module,
            "reason": facts.pop("reason", ""), "facts": facts}


def build(items, **inv):
    return generate.Build({"items": items, "mise": "2026.10.25", "machine": {"hostname": "box"}, **inv},
                          "/home/me", "2026-11-07")


class TestToml(unittest.TestCase):
    def test_unreachable_repo_is_cloned_softly_in_the_task(self):
        b = build([it("repo", "~/Work/gone", path="~/Work/gone", url="https://example.com/gone.git", reachable=False),
                   it("repo", "~/Work/here", path="~/Work/here", url="https://example.com/here.git", reachable=True)])
        toml = b.toml("")
        self.assertIn('"~/Work/here" = { url = "https://example.com/here.git" }', toml)
        self.assertNotIn("gone.git", toml)
        task = "\n".join(b.task_lines(b.mine("")))
        self.assertIn('git clone --quiet "https://example.com/gone.git" "$HOME/Work/gone" 2>/dev/null ||', task)
        self.assertIn('| tee -a "${LATER_FILE:-/dev/null}"', task)  # listed at the end of the restore

    def test_repo_addresses_work_on_a_new_machine(self):
        # A new machine has no SSH key on GitHub yet, and a password never goes in the repo.
        b = build([it("repo", "~/Work/a", path="~/Work/a", url="git@github.com:me/a.git"),
                   it("repo", "~/Work/b", path="~/Work/b", url="ssh://git@github.com/me/b"),
                   it("repo", "~/Work/c", path="~/Work/c", url="https://me:hunter22@github.com/me/c.git"),
                   it("repo", "~/Work/d", path="~/Work/d", url="git@gitlab.com:me/d.git"),
                   it("repo", "~/Work/e", path="~/Work/e", url="https://me:hunter22@git.example.com/e.git")])
        toml = b.toml("")
        task = "\n".join(b.task_lines(b.mine("")))
        self.assertIn('"~/Work/a" = { url = "https://github.com/me/a.git" }', toml)
        self.assertIn('"~/Work/b" = { url = "https://github.com/me/b.git" }', toml)
        self.assertIn('"~/Work/c" = { url = "https://github.com/me/c.git" }', toml)
        # Other hosts need their own login: tried in the task, where failing does not stop the run.
        self.assertNotIn("gitlab", toml)
        self.assertIn('git clone --quiet "git@gitlab.com:me/d.git"', task)
        self.assertIn('git clone --quiet "https://git.example.com/e.git"', task)
        self.assertNotIn("hunter22", toml + task)

    def test_private_dotfiles_keep_their_permissions(self):
        b = build([it("identity", "ssh-config", path="~/.ssh/config", mode="600"),
                   it("config", "~/.config/app.conf", path="~/.config/app.conf", mode="644")])
        toml = b.toml("")
        self.assertIn('"~/.ssh/config" = { source = "home/.ssh/config", mode = "copy", permissions = "0600" }', toml)
        self.assertIn('"~/.config/app.conf" = { source = "home/.config/app.conf", mode = "copy" }', toml)

    def test_oneshot_services_stay_stopped(self):
        b = build([it("service", "rapl.service", unit="rapl.service", reason="A oneshot unit"),
                   it("service", "agent.service", unit="agent.service", scope="user"),
                   it("masked-unit", "foo.service", path="/etc/systemd/system/foo.service")])
        toml = b.toml("")
        self.assertIn('[bootstrap.services."rapl"]\nstate = "stopped"\nenabled = true', toml)
        self.assertIn('[bootstrap.services."agent"]\nscope = "user"\nstate = "running"', toml)
        self.assertIn('[bootstrap.services."foo.service"]\nstate = "stopped"\nenabled = false\nmasked = true', toml)


class TestRepo(unittest.TestCase):
    def generate(self, items, decisions=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out"
        out.mkdir()
        (out / "inventory.json").write_text(json.dumps({
            "schema": 1, "generated": "now", "mise": "2026.10.25", "items": items,
            "machine": {"hostname": "box", "vendor": "Framework", "product": "Laptop 13 (Intel Core Ultra)", "cpu": "intel"}}))
        args = ["--out", str(out), "--allow-undecided", str(Path(tmp.name) / "repo")]
        if decisions:
            (out / "decisions.json").write_text(json.dumps({"schema": 1, "inventory": "now", "decisions": decisions}))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(generate.main(args), 0)
        return Path(tmp.name) / "repo"

    def test_module_tasks_run_only_where_detect_matches(self):
        repo = self.generate([it("link", "~/bin/fw", "module", "framework", path="~/bin/fw", target="~/Work/fw/bin/fw")])
        toml = (repo / "mise.toml").read_text()
        self.assertIn('if modules/framework/detect; then\n  mkdir -p "$HOME/.local/bin" "$HOME/bin"\n  ln -sfn', toml)
        detect = (repo / "modules/framework/detect").read_text()
        self.assertIn("== Framework ]]", detect)
        self.assertIn(r"== Laptop\ 13* ]]", detect)

    def test_rsync_plugins_bring_rsync(self):
        repo = self.generate([it("plugin", "me.bar", path="~/.config/omarchy/plugins/me.bar", deploy="rsync",
                                 source="~/Work/bar/plugin")])
        toml = (repo / "mise.toml").read_text()
        self.assertIn('"pacman:rsync" = "latest"', toml)
        self.assertIn('rsync -ac --delete "$HOME/Work/bar/plugin/" "$HOME/.config/omarchy/plugins/me.bar/"', toml)

    def test_decisions_override_and_undecided_are_left_out(self):
        repo = self.generate([it("package", "ripgrep", "review", source="pacman"),
                              it("package", "fd", "review", source="pacman")],
                             decisions={"package:ripgrep": {"class": "carry"}})
        toml = (repo / "mise.toml").read_text()
        self.assertIn('"pacman:ripgrep" = "latest"', toml)
        self.assertNotIn("pacman:fd", toml)

    def test_apps_come_last_unless_marked_first(self):
        repo = self.generate([it("package", "spotify", "step", source="pacman", installer="omarchy-install-service-spotify"),
                              it("package", "voxtype-bin", "step", source="aur", installer="omarchy-install-dictation-voxtype")],
                             decisions={"package:voxtype-bin": {"class": "step", "first": True}})
        steps = sorted(p.name for p in (repo / "steps").iterdir())
        self.assertLess(steps.index("35-omarchy-installers-first.sh"), steps.index("40-bootstrap.sh"))
        self.assertLess(steps.index("40-bootstrap.sh"), steps.index("80-apps.sh"))
        first = (repo / "steps/35-omarchy-installers-first.sh").read_text()
        last = (repo / "steps/80-apps.sh").read_text()
        self.assertIn('"voxtype-bin omarchy-install-dictation-voxtype"', first)
        self.assertNotIn("spotify", first)
        self.assertIn('"spotify omarchy-install-service-spotify"', last)
        self.assertIn('header "Apps"', last)
        self.assertNotIn("#TITLE#", first + last)

    def test_questions_come_first_and_nothing_waits_mid_run(self):
        repo = self.generate([it("identity", "ssh-keys", "step"), it("identity", "tailscale", "step"),
                              it("package", "tailscale", "carry"), it("identity", "fingerprint", "step")])
        steps = sorted(p.name for p in (repo / "steps").iterdir())
        self.assertLess(steps.index("25-ssh-keys.sh"), steps.index("40-bootstrap.sh"))
        # A login or a finger on the reader would stop the run: listed for afterwards instead.
        for name in ("60-tailscale.sh", "70-fingerprint.sh"):
            text = (repo / "steps" / name).read_text()
            self.assertIn("later ", text)
            self.assertNotIn("ask ", text)
            self.assertNotIn("attempt ", text)


    def test_missing_files_are_reported_as_missing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out"
        out.mkdir()
        (out / "inventory.json").write_text(json.dumps({"schema": 1, "generated": "now", "items": [
            it("config", "~/.config/gone.conf", path="~/.config/gone.conf")], "machine": {}}))
        with redirect_stdout(io.StringIO()) as report:
            generate.main(["--out", str(out), str(Path(tmp.name) / "repo")])
        self.assertIn("Missing on this machine", report.getvalue())
        self.assertNotIn("sudo cat", report.getvalue())


class TestQuoting(unittest.TestCase):
    def test_shell_word_matches_printf_q(self):
        self.assertEqual(generate.shell_word("Laptop 13 Pro"), r"Laptop\ 13\ Pro")
        self.assertEqual(generate.shell_word("Framework"), "Framework")
        self.assertEqual(generate.shell_word(""), "''")


if __name__ == "__main__":
    unittest.main()
