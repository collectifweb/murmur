"""M7c — installer le bundle, et refuser de le casser par mégarde.

Tout est simulé : `clang` et `codesign` n'existent pas sur la machine de
développement, et ce qu'on vérifie ici est la **décision** — installer, ne rien
faire, ou s'arrêter — pas ce que macOS en fait. Cette partie-là est mesurée par
M7-0 sur un vrai Mac.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import macos_desktop, macos_install


class CdhashTest(unittest.TestCase):
    def test_the_fingerprint_is_read_off_stderr(self):
        # `codesign -dvvv` écrit tout sur stderr : le lire sur stdout seulement
        # rendrait « empreinte illisible » sur un bundle parfaitement signé.
        done = mock.Mock(stdout="", stderr="Identifier=ca.collectifweb.aparte\nCDHash=ABC123def\n")
        with mock.patch.object(macos_install.subprocess, "run", return_value=done):
            self.assertEqual(macos_install.read_cdhash(Path("/x.app")), "abc123def")

    def test_an_unreadable_bundle_answers_none_rather_than_guessing(self):
        with mock.patch.object(macos_install.subprocess, "run", side_effect=OSError):
            self.assertIsNone(macos_install.read_cdhash(Path("/x.app")))

    def test_the_reference_lives_outside_the_bundle(self):
        # La ranger dedans modifierait précisément ce qu'elle prétend surveiller.
        reference = macos_install.cdhash_reference_path()
        self.assertNotIn(macos_desktop.BUNDLE_NAME, str(reference))
        self.assertEqual(reference.name, macos_install.CDHASH_FILE)


class InstallTest(unittest.TestCase):
    """Les trois issues, et la seule qui doit s'arrêter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.destination = self.home / "Applications" / macos_desktop.BUNDLE_NAME
        patches = [
            mock.patch.object(macos_desktop, "bundle_path", return_value=self.destination),
            mock.patch.object(macos_install, "_run"),
            mock.patch.object(
                macos_install, "cdhash_reference_path", return_value=self.home / "reference"
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _install(self, fresh, installed=None, force=False):
        # read_cdhash est appelé sur le bundle fraîchement bâti, puis sur celui en place.
        with mock.patch.object(macos_install, "read_cdhash", side_effect=[fresh, installed]):
            return macos_install.install_app("/opt/homebrew/opt/aparte/libexec/bin/python3",
                                             force=force)

    def test_a_first_install_puts_the_bundle_in_place(self):
        result = self._install("aaa")
        self.assertEqual(result["outcome"], "installed")
        self.assertTrue(self.destination.exists())
        self.assertEqual((self.home / "reference").read_text().strip(), "aaa")

    def test_the_same_fingerprint_changes_nothing(self):
        self._install("aaa")
        before = (self.destination / "Contents" / "Info.plist").stat().st_mtime_ns
        result = self._install("aaa", installed="aaa")
        self.assertEqual(result["outcome"], "unchanged")
        self.assertEqual(
            (self.destination / "Contents" / "Info.plist").stat().st_mtime_ns, before
        )

    def test_a_different_fingerprint_stops_and_says_what_it_would_cost(self):
        # Le cas qui compte : remplacer ferait oublier les autorisations à macOS,
        # en laissant les cases cochées. Ça se dit avant, pas après.
        self._install("aaa")
        with self.assertRaises(macos_install.InstallError) as raised:
            self._install("bbb", installed="aaa")
        message = str(raised.exception)
        self.assertIn("--force", message)
        self.assertIn("forget", message)

    def test_force_replaces_it_and_records_the_new_fingerprint(self):
        self._install("aaa")
        result = self._install("bbb", installed="aaa", force=True)
        self.assertEqual(result["outcome"], "replaced")
        self.assertEqual((self.home / "reference").read_text().strip(), "bbb")

    def test_an_unsignable_bundle_is_never_presented_as_installed(self):
        with self.assertRaises(macos_install.InstallError):
            self._install(None)
        self.assertFalse(self.destination.exists())

    def test_the_c_source_never_ships_inside_the_bundle(self):
        # Il serait signé avec le reste : l'empreinte dépendrait de lui.
        self._install("aaa")
        self.assertEqual(list(self.destination.rglob("*.c")), [])


class UninstallTest(unittest.TestCase):
    """`brew uninstall` laisse le bundle en place — il vit hors du préfixe, exprès."""

    def test_it_removes_the_bundle_and_forgets_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            destination = home / "Applications" / macos_desktop.BUNDLE_NAME
            destination.mkdir(parents=True)
            reference = home / "reference"
            reference.write_text("aaa")
            with mock.patch.object(macos_desktop, "bundle_path", return_value=destination):
                with mock.patch.object(
                    macos_install, "cdhash_reference_path", return_value=reference
                ):
                    self.assertTrue(macos_install.uninstall_app())
                    self.assertFalse(destination.exists())
                    self.assertFalse(reference.exists())
                    self.assertFalse(macos_install.uninstall_app())


class OpenTest(unittest.TestCase):
    def test_it_goes_through_launch_services_not_the_launcher(self):
        # Lancer l'exécutable à la main ferait de ce processus-ci le responsable,
        # et tout l'intérêt du bundle est que ce soit LaunchServices.
        with mock.patch.object(macos_install, "_run") as run:
            macos_install.open_app()
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/open")


class PendingVerdictTest(unittest.TestCase):
    """Les deux choix que M7-0 doit confirmer sont nommés, à un seul endroit."""

    def test_the_two_open_choices_are_named_constants(self):
        self.assertIn(
            macos_install.INSTALL_MODE, (macos_desktop.LAUNCH_EXEC, macos_desktop.LAUNCH_CHILD)
        )
        self.assertTrue(macos_install.INSTALL_IDENTITY)
