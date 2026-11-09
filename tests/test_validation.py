"""The validation tools' own parsing: bin/check, bin/check-builds and the VM harness."""

from __future__ import annotations

import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from omarchy_blueprint import check, check_builds

sys.path.insert(0, str(Path(__file__).resolve().parent / "vm"))
import harness  # noqa: E402

DASH = chr(0x2014)

PS = """\
    1     0 systemd         /sbin/init
  200     1 bash            /bin/bash /home/user/Work/my-omarchy/bootstrap.sh
  210   200 sudo            sudo pacman -S --needed foo
  211   210 pacman          pacman -S --needed foo
  220   200 sudo            sudo -n -v
  230   200 sudo            sudo true
  240   200 gum             gum confirm --default=false Include the framework module anyway?
  241   200 gum             gum style --bold Packages
  250     1 bash            /bin/bash /usr/bin/omarchy-show-done 0
  260     1 bash            bash -c ps -eo pid=,ppid=,comm=,args=; grep my-omarchy/bootstrap
"""


class TestHarness(unittest.TestCase):
    def setUp(self):
        self.procs = harness.parse_ps(PS)

    def test_questions_are_a_waiting_sudo_and_gum_prompts(self):
        self.assertEqual(harness.questions(self.procs), [
            "230 sudo password",
            "240 gum confirm --default=false Include the framework module anyway?"])

    def test_done_screen_gives_the_exit_code(self):
        self.assertEqual(harness.finished(self.procs), "0")
        self.assertIsNone(harness.finished(harness.parse_ps(PS.replace("omarchy-show-done", "omarchy-x"))))

    def test_left_running_does_not_count_the_command_that_looks(self):
        left = harness.left_running(self.procs, "my-omarchy")
        self.assertEqual([p.pid for p in left], [200, 220])

    def test_answers_first_match_wins(self):
        a = harness.Answers.parse("# comment\nsudo password\tpassword\nmodule anyway\tn\n^gum choose\tenter\n")
        self.assertEqual(a.find("230 sudo password"), "password")
        self.assertEqual(a.find("240 gum confirm --default=false Include the framework module anyway?"), "n")
        self.assertEqual(a.find("9 gum choose Stable Nightly"), "enter")
        self.assertIsNone(a.find("9 gum confirm Something new?"))

    def test_answers_reject_a_bad_line(self):
        with self.assertRaises(harness.Stop):
            harness.Answers.parse("Trust it y\n")
        with self.assertRaises(harness.Stop):
            harness.Answers.parse("Trust it\tyes\n")

    def test_default_answers_parse(self):
        harness.Answers.parse((Path(harness.HERE) / "answers.default").read_text())

    def test_short_drops_gum_options(self):
        self.assertEqual(harness.short("240 gum confirm --default=false Include the framework module anyway?"),
                         "Include the framework module anyway?")

    def test_log_finds_steps_across_pieces_and_the_later_list(self):
        log = harness.Log({"SSH key", "Apps"})
        self.assertEqual(log.feed("/r.log", b"start\n\x1b[1mSSH k"), [])
        self.assertEqual(log.feed("/r.log", b"ey\x1b[0m  \nmore\r\x1b[2KApps\n"), ["SSH key", "Apps"])
        log.feed("/r.log", b"    Left for you, whenever suits:\r\n  \xe2\x80\xa2 Run: sudo tailscale up\r\n\r\n    Log out\r\n")
        self.assertEqual(log.later, ["• Run: sudo tailscale up"])
        self.assertEqual(log.offset, len(b"start\n\x1b[1mSSH k") + len(b"ey\x1b[0m  \nmore\r\x1b[2KApps\n")
                         + len(b"    Left for you, whenever suits:\r\n  \xe2\x80\xa2 Run: sudo tailscale up\r\n\r\n    Log out\r\n"))

    def test_work_left_undone_is_fine_only_when_the_list_says_so(self):
        later = ['wl-kbptr did not build: see "A package that no longer builds" in README.md']
        plan = ["create     package:aur:wl-kbptr      missing     installed (any version)",
                "create     package:pacman:wl-kbptr-extra      missing     installed"]
        self.assertEqual(harness.unlisted(plan, later), [plan[1]])
        self.assertEqual(harness.unlisted(["yay -S --aur --noconfirm -- wl-kbptr"], later), [])
        self.assertEqual(harness.unlisted(["yay -S --aur --noconfirm -- wl-kbptr"], []),
                         ["yay -S --aur --noconfirm -- wl-kbptr"])

    def test_a_new_log_is_read_from_its_start(self):
        log = harness.Log({"Apps"})
        log.feed("/a.log", b"x\n")
        self.assertEqual(log.feed("/b.log", b"tail of a\n"), [])  # read at a's offset
        self.assertEqual(log.offset, 0)
        self.assertEqual(log.feed("/b.log", b"Apps\n"), ["Apps"])

    def test_poll_output_splits_and_its_own_command_has_no_marker(self):
        script = harness.poll_script(0)
        self.assertNotIn("::omarchy-log::", script)
        out = PS.encode() + b"\n::omarchy-log::\n/home/user/.local/state/x/restore-1.log\nApps\n"
        procs, name, chunk = harness.split_poll(out)
        self.assertEqual(len(procs), 10)
        self.assertEqual(name, "/home/user/.local/state/x/restore-1.log")
        self.assertEqual(chunk, b"Apps\n")

    def test_local_env_is_read_without_a_shell(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "local.env"
            env.write_text("# the VM\nVM_PASSWORD=a$b'c\nexport MIRROR_GITHUB_USER='me'\n")
            self.assertEqual(harness.read_env(env), {"VM_PASSWORD": "a$b'c", "MIRROR_GITHUB_USER": "me"})

    def test_every_character_of_a_password_can_be_typed(self):
        for ch in "aZ09 ~!@#$%^&*()_+{}|:\"<>?-=[]\\;',./`\n":
            harness.keys_for(ch)
        with self.assertRaises(harness.Stop):
            harness.keys_for("å")


class FakeQemu(threading.Thread):
    """A control socket that, like QEMU's, serves one client at a time."""

    def __init__(self, path: Path):
        super().__init__(daemon=True)
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen()

    def run(self):
        while True:
            conn, _ = self.server.accept()
            with conn, conn.makefile("rw") as f:
                f.write('{"QMP": {}}\n')
                f.flush()
                for _ in f:
                    f.write('{"return": {"status": "running"}}\n')
                    f.flush()


class TestQmp(unittest.TestCase):
    def test_each_connection_lets_the_next_one_in(self):
        with tempfile.TemporaryDirectory() as d:
            sock = Path(d) / "qmp.sock"
            FakeQemu(sock).start()
            for _ in range(3):
                with harness.QMP(sock, timeout=2) as q:
                    self.assertEqual(q.cmd("query-status")["status"], "running")


class TestCheck(unittest.TestCase):
    def test_em_dashes_are_found_outside_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.md").write_text("fine\nnot " + DASH + " fine\n")
            (root / "b.json").write_text('"' + DASH + '"')
            old, check.KIT = check.KIT, root
            try:
                self.assertEqual(check.em_dashes([Path("a.md"), Path("b.json")]), ["a.md:2: not " + DASH + " fine"])
            finally:
                check.KIT = old

    def test_offers_and_pending_lines(self):
        self.assertEqual(check.offers_in("\x1b[1mSSH key\x1b[0m\n  • Create a key\n  ✓ fine\n"),
                         ["  • Create a key"])
        self.assertEqual(check.pending_in("task\nyay -S foo\nunchanged\n"), ["yay -S foo"])


class TestCheckBuilds(unittest.TestCase):
    def test_aur_packages_from_every_mise_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "mise.toml").write_text('[bootstrap.packages]\n"aur:b" = "latest"\n"pacman:x" = "latest"\n')
            (root / "mise.framework.toml").write_text('[bootstrap.packages]\n"aur:a" = "latest"\n')
            self.assertEqual(check_builds.aur_packages(root), ["a", "b"])

    def test_error_lines_skip_makepkg_summary(self):
        log = "ok\n==> ERROR: A failure occurred in build().\nDependency \"opencv4\" not found\n"
        self.assertEqual(check_builds.error_lines(log), ['Dependency "opencv4" not found'])


if __name__ == "__main__":
    unittest.main()
