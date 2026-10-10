"""Regression tests for the six-account read-only WordPress migration inventory."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "hostinger_script_migration", ROOT / "scripts/hostinger_script_migration.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

EXPECTED_EXCLUSIONS = (
    "cf7-conditional-fields",
    "cf7-multi-step",
    "contact-form-7",
    "drag-and-drop-multiple-file-upload-contact-form-7",
    "open-rdw-kenteken-voertuiginformatie",
    "wpcf7-redirect",
)
ARCHIVE_DIGEST = "86b104f5107e2a69e70377b99328014d1e2401c7dca9c28ff3553aff211ac13f"


class HostingerScriptMigrationTests(unittest.TestCase):
    def test_six_excluded_plugins_are_pinned(self):
        policy = migration.load_policy()
        self.assertEqual(tuple(policy["hostinger-2"]["excluded_plugins"]), EXPECTED_EXCLUSIONS)
        self.assertEqual(policy["hostinger-2"]["legacy_sha256"], ARCHIVE_DIGEST)

    def test_policy_does_not_silently_accept_missing_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "policy.json"
            p.write_text('{"version":1,"hostinger-2":{"legacy_sha256":"' +
                         ARCHIVE_DIGEST + '","excluded_plugins":["contact-form-7"]}}')
            with self.assertRaises(migration.Blocked):
                migration.load_policy(p)

    def test_parse_requires_exact_structure_and_counts(self):
        data = {key: migration.ABSENT if key in migration.DIGEST_FIELDS else ("0" if key in ("MATCHING_EXCLUSION_FILES", "SOURCE_ACCOUNT_SPECIFIC") else "1")
                for key in migration.FIELDS}
        valid = "".join(f"SCRIPT_AUDIT\t{k}\t{v}\n" for k, v in data.items())
        self.assertEqual(migration.parse_ssh_output(valid), data)
        for broken in (
            valid + "uncontrolled SSH output\n",
            valid + "SCRIPT_AUDIT\tDOMAIN_DIRS\t2\n",
            valid.replace("SCRIPT_AUDIT\tWP_CLI\t1\n", ""),
            valid.replace("SCRIPT_AUDIT\tDOMAIN_DIRS\t1\n",
                          "SCRIPT_AUDIT\tDOMAIN_DIRS\t1;rm -rf /\n"),
            valid.replace(migration.ABSENT, "invalid", 1),
        ):
            with self.subTest(broken=broken[:65]):
                with self.assertRaises(migration.Blocked):
                    migration.parse_ssh_output(broken)

    def test_hostinger2_wrong_checksum_blocks_migration(self):
        inventory = {key: migration.ABSENT if key in migration.DIGEST_FIELDS else ("0" if key in ("MATCHING_EXCLUSION_FILES", "SOURCE_ACCOUNT_SPECIFIC") else "1")
                     for key in migration.FIELDS}
        with contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertFalse(migration.evaluate(
                "hostinger-2", inventory, 0, migration.load_policy()))
        self.assertIn("Historisch exclusieprofiel ergens buiten webroot gevonden: NEE", log.getvalue())
        self.assertNotIn("cf7-conditional-fields", log.getvalue())

    def test_hostinger2_matching_checksum_allows_audit_only(self):
        inventory = {key: migration.ABSENT if key in migration.DIGEST_FIELDS else ("0" if key in ("MATCHING_EXCLUSION_FILES", "SOURCE_ACCOUNT_SPECIFIC") else "1")
                     for key in migration.FIELDS}
        inventory["HOME_EXCLUSION"] = ARCHIVE_DIGEST
        with contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertTrue(migration.evaluate(
                "hostinger-2", inventory, 0, migration.load_policy()))
        self.assertIn("AUDIT_OK: alleen gelezen", log.getvalue())

    def test_remote_inspection_reads_existing_scripts_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "domains"
            root.mkdir()
            script = root / "update_wordpress.sh"
            legacy = home / "update_wordpress_exclusion.sh"
            script.write_text("#!/usr/bin/env bash\necho 'PRIVATE DOMAIN: example.com'\n")
            legacy.write_text("#!/usr/bin/env bash\nprintf 'excluded plugin data'\n")
            original1, original2 = script.read_bytes(), legacy.read_bytes()
            p = subprocess.run(["bash", "-s", "--", migration.ABSENT], input=migration.REMOTE,
                               text=True, capture_output=True, timeout=10,
                               env={**os.environ, "HOME": tmp})
            self.assertEqual(p.returncode, 0, p.stderr)
            result = migration.parse_ssh_output(p.stdout)
            self.assertEqual(result["DOMAINS_SCRIPT"], hashlib.sha256(original1).hexdigest())
            self.assertEqual(result["HOME_EXCLUSION"], hashlib.sha256(original2).hexdigest())
            self.assertEqual(script.read_bytes(), original1)
            self.assertEqual(legacy.read_bytes(), original2)
            self.assertNotIn("example.com", p.stdout)
            self.assertNotIn("excluded plugin data", p.stdout)

    def test_symlink_script_stops_before_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "domains"
            root.mkdir()
            (root / "update_wordpress.sh").symlink_to("/etc/passwd")
            p = subprocess.run(["bash", "-s", "--", migration.ABSENT], input=migration.REMOTE,
                               text=True, capture_output=True, timeout=10,
                               env={**os.environ, "HOME": tmp})
            self.assertNotEqual(p.returncode, 0)

    def test_invalid_bash_script_is_diagnosed_without_running_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "domains"
            root.mkdir()
            path = root / "update_wordpress.sh"
            path.write_text("#!/usr/bin/env bash\nif then\n")
            p = subprocess.run(["bash", "-s", "--", migration.ABSENT], input=migration.REMOTE,
                               text=True, capture_output=True, timeout=10,
                               env={**os.environ, "HOME": tmp})
            self.assertEqual(p.returncode, 0, p.stderr)
            result = migration.parse_ssh_output(p.stdout)
            self.assertEqual(result["DOMAINS_SCRIPT_SYNTAX"], "0")
            with contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertFalse(migration.evaluate("hostinger-5", result, p.returncode,
                                                    migration.load_policy()))
            self.assertIn("ongeldige Bash-syntax", log.getvalue())

    def test_legacy_exclusion_found_outside_expected_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "domains").mkdir()
            folder = home / "tools"
            folder.mkdir()
            old = folder / "wordpress_legacy.sh"
            old.write_text("#!/usr/bin/env bash\nprintf 'OLD PRIVATE EXCLUSION'\n")
            expected = hashlib.sha256(old.read_bytes()).hexdigest()
            p = subprocess.run(["bash", "-s", "--", expected], input=migration.REMOTE,
                               text=True, capture_output=True, timeout=10,
                               env={**os.environ, "HOME": tmp})
            self.assertEqual(p.returncode, 0, p.stderr)
            parsed = migration.parse_ssh_output(p.stdout)
            self.assertEqual(parsed["MATCHING_EXCLUSION_FILES"], "1")
            self.assertNotIn(str(folder), p.stdout)
            self.assertNotIn("PRIVATE EXCLUSION", p.stdout)

    def test_domain_names_fingerprint_without_disclosure(self):
        digests = []
        for names in (("one.example", "two.example"), ("one.example", "two.example"),
                      ("one.example", "three.example")):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "domains"
                root.mkdir()
                for name in names:
                    (root / name).mkdir()
                p = subprocess.run(["bash", "-s", "--", migration.ABSENT],
                                   input=migration.REMOTE, text=True, capture_output=True,
                                   env={**os.environ, "HOME": tmp}, timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)
                parsed = migration.parse_ssh_output(p.stdout)
                digests.append(parsed["DOMAIN_NAMES_SHA256"])
                self.assertNotIn("one.example", p.stdout)
        self.assertEqual(digests[0], digests[1])
        self.assertNotEqual(digests[0], digests[2])

    def test_new_workflow_never_runs_updater_or_writes(self):
        workflow = (ROOT / ".github/workflows/hostinger-wordpress-migration-audit.yml").read_text()
        for required in ("  push:", "workflow_dispatch:", "branches: [main]",
                         "name: " + "${{ matrix.hosting }}",
                         "max-parallel: 1", "permissions:\n  contents: read",
                         "scripts/hostinger_script_migration.py"):
            self.assertIn(required, workflow)
        for forbidden in ("scripts/wordpress_maintenance.py update",
                          "rsync --delete", "StrictHostKeyChecking=no",
                          "bash \"$HOME/domains/update_wordpress.sh\"",
                          "scp ", "curl -X POST"):
            self.assertNotIn(forbidden, workflow)
        for secret in ("HOSTINGER_SITES_JSON", "HOSTINGER_SSH_PRIVATE_KEY",
                       "HOSTINGER_SSH_KNOWN_HOSTS"):
            self.assertIn("secrets." + secret, workflow)


if __name__ == "__main__":
    unittest.main()
