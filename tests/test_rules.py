"""Classification rules, each tested against a fake machine.

Most of these are bugs that happened on real machines. Run with:

  python3 -m unittest discover tests
"""

from __future__ import annotations

import unittest

from omarchy_blueprint.collectors import commands, configs, packages, services
from omarchy_blueprint.env import is_junk

from fake import Machine


def by_id(items):
    return {it["id"]: it for it in items}


class Case(unittest.TestCase):
    def setUp(self):
        self.m = Machine()
        self.addCleanup(self.m.close)


class TestCorpus(Case):
    def test_reads_commands_behind_symlinks(self):
        # Omarchy's bin/ holds symlinks into /usr/bin. Skipping symlinks once meant
        # no Omarchy command was ever read.
        real = self.m.write(self.m.root / "usr/bin/omarchy-install-thing", 'ln -s x "$HOME/.local/bin/thing"\n')
        self.m.link(self.m.omarchy / "bin/omarchy-install-thing", real)
        self.assertTrue(self.m.env().corpus.mentions("local/bin/thing"))

    def test_command_needs_local_bin_nearby(self):
        # "contacts" appears in contacts.google.com, far from any ~/.local/bin.
        self.m.write(self.m.omarchy / "applications/Contacts.desktop", "Exec=omarchy-launch-webapp https://contacts.google.com/\n")
        self.m.write(self.m.omarchy / "bin/omarchy-install-hermes", "# filler\n" * 10 +
                     'for command in hermes hermes-agent hermes-acp; do\n  existing="$HOME/.local/bin/$command"\ndone\n' + "# filler\n" * 10)
        corpus = self.m.env().corpus
        self.assertFalse(corpus.writes_command("contacts"))
        self.assertTrue(corpus.writes_command("hermes-acp"))

    def test_commands_collector_skips_omarchy_commands(self):
        self.m.write(self.m.omarchy / "bin/omarchy-install-tool", 'cp tool "$HOME/.local/bin/tool"\n')
        self.m.write(self.m.home / ".local/bin/tool", "#!/bin/sh\necho hi\n", 0o755)
        self.m.write(self.m.home / "bin/mine", "#!/bin/sh\necho mine\n", 0o755)
        items = by_id(commands.collect(self.m.env()))
        self.assertEqual(items["command:~/.local/bin/tool"]["class"], "skip")
        self.assertEqual(items["command:~/bin/mine"]["class"], "carry")


class TestJunk(Case):
    def test_any_backup_component(self):
        env = self.m.env()
        self.assertTrue(is_junk(env, self.m.home / ".config/app.bak/settings.conf"))
        self.assertTrue(is_junk(env, self.m.home / ".config/app/settings.conf.bak-2026"))
        self.assertFalse(is_junk(env, self.m.home / ".config/app/settings.conf"))


class TestConfigs(Case):
    def test_edited_default_is_carried_and_backup_is_not(self):
        self.m.write(self.m.omarchy / "config/app/app.conf", "a = 1\n")
        self.m.write(self.m.home / ".config/app/app.conf", "a = 2\n")
        self.m.write(self.m.home / ".config/app/app.conf.bak", "a = 0\n")
        self.m.answer("diff", out="1c1\n< a = 1\n---\n> a = 2\n", rc=1)
        items = by_id(configs.collect(self.m.env()))
        self.assertEqual(items["config:~/.config/app/app.conf"]["class"], "carry")
        self.assertEqual(items["config:~/.config/app/app.conf"]["facts"]["lines_changed"], 2)
        self.assertNotIn("config:~/.config/app/app.conf.bak", items)

    def test_dots_tracked_files_are_left_to_dots(self):
        self.m.write(self.m.omarchy / "config/app/app.conf", "a = 1\n")
        self.m.write(self.m.home / ".config/app/app.conf", "a = 2\n")
        self.m.answer("mise", "dot", "paths", out=f"{self.m.home}/.config/app/app.conf  tracked\n")
        items = by_id(configs.collect(self.m.env()))
        self.assertEqual(items["config:~/.config/app/app.conf"]["class"], "skip")

    def test_settings_of_omarchy_default_apps_say_so(self):
        # omawrite and omacalc are on every Omarchy install and write ~/.config/Omacom/*.conf themselves.
        self.m.write(self.m.omarchy / "install/omarchy-base.packages", "omawrite\nomacalc\n")
        self.m.write(self.m.home / ".config/Omacom/omawrite.conf", "[window]\nwidth=1517\n")
        self.m.write(self.m.home / ".config/Omacom/omacalc.conf", "")
        self.m.write(self.m.home / ".config/mytool/settings.toml", "x = 1\n")
        items = by_id(configs.collect(self.m.env()))
        write = items["config:~/.config/Omacom/omawrite.conf"]
        self.assertEqual(write["class"], "review")
        self.assertIn("omawrite, one of Omarchy's default apps", write["reason"])
        self.assertEqual(items["config:~/.config/Omacom/omacalc.conf"]["class"], "skip")
        self.assertIn("Not shipped by Omarchy", items["config:~/.config/mytool/settings.toml"]["reason"])

    def test_monitors_go_to_a_module(self):
        self.m.write(self.m.omarchy / "config/hypr/monitors.lua", "-- default\n")
        self.m.write(self.m.home / ".config/hypr/monitors.lua", "monitor(...)\n")
        items = by_id(configs.collect(self.m.env()))
        self.assertEqual(items["config:~/.config/hypr/monitors.lua"]["class"], "module")
        self.assertEqual(items["config:~/.config/hypr/monitors.lua"]["module"], "machine")

    def test_desktop_entry_with_rewritten_exec_is_a_note(self):
        entry = "[Desktop Entry]\nName=YouTube\nExec=omarchy-launch-webapp https://youtube.com/\nIcon=yt\n"
        self.m.write(self.m.omarchy / "applications/YouTube.desktop", entry)
        self.m.write(self.m.home / ".local/share/applications/YouTube.desktop",
                     entry.replace("omarchy-launch-webapp", "/opt/profiles/bin/profiler webapp open"))
        it = by_id(configs.collect(self.m.env()))["desktop-entry:~/.local/share/applications/YouTube.desktop"]
        self.assertEqual(it["class"], "note")
        self.assertEqual(it["facts"]["rewritten_by"], "profiler")

    def test_link_handlers_are_left_to_the_app(self):
        self.m.write(self.m.home / ".local/share/applications/app-url.desktop",
                     "[Desktop Entry]\nName=App\nExec=/usr/bin/app %u\nNoDisplay=true\nMimeType=x-scheme-handler/app;\n")
        it = by_id(configs.collect(self.m.env()))["desktop-entry:~/.local/share/applications/app-url.desktop"]
        self.assertEqual(it["class"], "skip")

    def test_hand_made_desktop_entry_is_carried(self):
        self.m.write(self.m.home / ".local/share/applications/notes.desktop",
                     "[Desktop Entry]\nName=Notes\nExec=xdg-terminal-exec nvim ~/notes.md\n")
        it = by_id(configs.collect(self.m.env()))["desktop-entry:~/.local/share/applications/notes.desktop"]
        self.assertEqual(it["class"], "carry")


class TestServices(Case):
    def setUp(self):
        super().setUp()
        m = self.m
        m.answer("systemctl", "list-unit-files", out="NetworkManager.service enabled enabled\n"
                 "NetworkManager-dispatcher.service enabled disabled\nmy-tweak.service enabled disabled\n"
                 "my-daemon.service enabled disabled\n")
        m.answer("systemctl", "cat", "NetworkManager.service", out="[Install]\nAlso=NetworkManager-dispatcher.service\n")
        m.answer("systemctl", "show", out="FragmentPath=/usr/lib/systemd/system/NetworkManager.service\n"
                 "ActiveState=active\nType=dbus\n\n"
                 "FragmentPath=/usr/lib/systemd/system/NetworkManager-dispatcher.service\n"
                 "ActiveState=active\nType=dbus\n\nFragmentPath=/etc/systemd/system/my-tweak.service\n"
                 "ActiveState=inactive\nType=oneshot\n\nFragmentPath=/etc/systemd/system/my-daemon.service\n"
                 "ActiveState=active\nType=simple\n")

    def test_also_units_follow_their_parent(self):
        items = by_id(services.collect(self.m.env()))
        self.assertEqual(items["service:NetworkManager-dispatcher.service"]["class"], "skip")
        self.assertNotIn("service:NetworkManager.service", items)  # preset enables it

    def test_inactive_oneshot_is_carried_stopped(self):
        items = by_id(services.collect(self.m.env()))
        self.assertEqual(items["service:my-tweak.service"]["class"], "carry")
        self.assertIn('state = "stopped"', items["service:my-tweak.service"]["reason"])
        self.assertEqual(items["service:my-daemon.service"]["reason"], "Enabled by you.")

    def test_units_omarchy_enables_are_skipped(self):
        self.m.write(self.m.omarchy / "install/services.sh", "systemctl enable my-daemon.service\n")
        items = by_id(services.collect(self.m.env()))
        self.assertEqual(items["service:my-daemon.service"]["class"], "skip")


class TestIdentity(Case):
    def test_tailscale_is_left_to_omarchys_installer(self):
        # omarchy-install-service-tailscale runs tailscale up itself.
        from omarchy_blueprint.collectors import identity
        self.m.which["tailscale"] = "/usr/bin/tailscale"
        self.m.answer("tailscale", "status", "--json", out='{"BackendState": "Running"}')
        it = by_id(identity.collect(self.m.env()))["identity:tailscale"]
        self.assertEqual(it["class"], "skip")
        self.assertIn("omarchy-install-service-tailscale", it["reason"])


class TestPackages(Case):
    def test_installers_lists_and_removals(self):
        m = self.m
        m.write(m.omarchy / "install/omarchy-base.packages", "# base\nhyprland\nmako\n")
        m.write(m.omarchy / "install/hardware.sh", "omarchy-pkg-add fprintd\n")
        m.write(m.omarchy / "bin/omarchy-install-tailscale", "omarchy-pkg-add tailscale\n")
        m.answer("pacman", "-Qqe", out="hyprland\ntailscale\nfprintd\nripgrep\nyay-thing\n")
        m.answer("pacman", "-Qqm", out="yay-thing\n")
        m.answer("pacman", "-T", out="mako\n", rc=127)
        m.answer("pacman", "-Sl", out="omarchy ripgrep 14.1-1 [installed]\nextra ripgrep 14.0-1\nextra fprintd 1.0-1\n")
        items = by_id(packages.collect(m.env()))
        self.assertNotIn("package:hyprland", items)
        self.assertEqual(items["package:tailscale"]["class"], "step")
        self.assertEqual(items["package:tailscale"]["facts"]["installer"], "omarchy-install-tailscale")
        self.assertEqual(items["package:fprintd"]["class"], "skip")
        self.assertEqual(items["package:ripgrep"]["class"], "carry")
        self.assertEqual(items["package:yay-thing"]["facts"]["source"], "aur")
        self.assertEqual(items["package:ripgrep"]["facts"]["repo"], "omarchy")  # first repo wins
        self.assertNotIn("repo", items["package:yay-thing"]["facts"])
        self.assertEqual(items["package-removed:mako"]["class"], "review")

    def test_packages_an_omarchy_setup_installs_are_left_to_it(self):
        m = self.m
        m.write(m.omarchy / "bin/omarchy-setup-security-fingerprint",
                "if omarchy-pkg-missing libfprint-git fprintd usbutils; then\n"
                "  sudo pacman -S --needed --noconfirm --ask 4 -- libfprint-git fprintd usbutils\nfi\n")
        m.answer("pacman", "-Qqe", out="libfprint\nfprintd\nusbutils\nripgrep\n")
        m.answer("pacman", "-Si", out="Name            : libfprint-git\n"
                 "Provides        : libfprint=1.94.100.r10  libfprint-2.so=2-64\n\nName            : fprintd\nProvides        : None\n")
        items = by_id(packages.collect(m.env()))
        for pkg in ("libfprint", "fprintd", "usbutils"):
            self.assertEqual(items[f"package:{pkg}"]["class"], "skip", pkg)
            self.assertEqual(items[f"package:{pkg}"]["facts"]["setup"], "omarchy-setup-security-fingerprint")
        self.assertIn("as libfprint-git, which replaces it", items["package:libfprint"]["reason"])
        self.assertNotIn("4", {k.split(":")[1] for k in items})
        self.assertEqual(items["package:ripgrep"]["class"], "carry")

    def test_foreign_package_missing_from_the_aur_is_a_note(self):
        m = self.m
        m.answer("pacman", "-Qqe", out="yay-thing\nhomemade\n")
        m.answer("pacman", "-Qqm", out="yay-thing\nhomemade\n")
        m.answer("curl", out='{"resultcount":1,"results":[{"Name":"yay-thing"}]}')
        items = by_id(packages.collect(m.env(offline=False)))
        self.assertEqual(items["package:yay-thing"]["class"], "carry")
        self.assertEqual(items["package:homemade"]["class"], "note")
        self.assertIs(items["package:homemade"]["facts"]["in_aur"], False)
        # Offline, nothing is judged: both stay as found.
        self.assertEqual(by_id(packages.collect(m.env()))["package:homemade"]["class"], "carry")

    def test_aur_package_flagged_out_of_date_says_so(self):
        m = self.m
        m.answer("pacman", "-Qqe", out="stale\nfresh\n")
        m.answer("pacman", "-Qqm", out="stale\nfresh\n")
        m.answer("curl", out='{"results":[{"Name":"stale","OutOfDate":1767225600},{"Name":"fresh","OutOfDate":null}]}')
        items = by_id(packages.collect(m.env(offline=False)))
        self.assertEqual(items["package:stale"]["class"], "carry")
        self.assertIn("check-builds", items["package:stale"]["reason"])
        self.assertTrue(items["package:stale"]["facts"]["aur_out_of_date"].startswith("2026-01-0"))
        self.assertNotIn("aur_out_of_date", items["package:fresh"]["facts"])


if __name__ == "__main__":
    unittest.main()
