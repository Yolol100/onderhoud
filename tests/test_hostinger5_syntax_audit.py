"""Tests for privacy-safe and read-only Hostinger-5 syntax checks."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hostinger5_syntax_audit as audit


class Hostinger5SyntaxAuditTests(unittest.TestCase):
    def probe(self, script_bytes):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "domains" / "update_wordpress.sh"
            target.parent.mkdir()
            target.write_bytes(script_bytes)
            run = subprocess.run(
                ["bash", "-s", "--"], input=audit.REMOTE, text=True,
                capture_output=True, env={**os.environ, "HOME": temp},
                timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(target.read_bytes(), script_bytes)
            self.assertNotIn("SECRET_SAMPLE_VALUE", run.stdout)
            report = audit.parse_remote_output(run.stdout)
            self.assertEqual(report["SHA256"], hashlib.sha256(script_bytes).hexdigest())
            return report, run.stdout

    def test_valid_syntax_is_untouched(self):
        report, stdout = self.probe(
            b"#!/usr/bin/env bash\necho 'SECRET_SAMPLE_VALUE'\n")
        self.assertEqual(report["STATUS"], "OK")
        self.assertEqual(report["CATEGORY"], "NONE")
        self.assertEqual(report["LINE"], "0")
        self.assertEqual(report["NORMALIZED_OK"], "1")
        self.assertNotIn("SECRET_SAMPLE_VALUE", stdout)

    def test_syntax_error_reports_allowlisted_category_not_source(self):
        report, stdout = self.probe(
            b"#!/usr/bin/env bash\nif then\n# SECRET_SAMPLE_VALUE\n")
        self.assertEqual(report["STATUS"], "INVALID")
        self.assertNotEqual(report["CATEGORY"], "NONE")
        self.assertTrue(report["LINE"].isdecimal())
        self.assertEqual(report["NORMALIZED_OK"], "0")
        self.assertNotIn("if then", stdout)

    def test_crlf_only_corruption_is_detected_without_rewrite(self):
        report, _ = self.probe(
            b"#!/usr/bin/env bash\r\nif true; then\r\n  echo ok\r\nfi\r\n")
        self.assertEqual(report["STATUS"], "INVALID")
        self.assertEqual(report["NORMALIZED_OK"], "1")

    def test_symlink_script_never_examined(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "domains"
            root.mkdir()
            (root / "update_wordpress.sh").symlink_to("/etc/passwd")
            run = subprocess.run(["bash", "-s", "--"], input=audit.REMOTE,
                                 text=True, capture_output=True,
                                 env={**os.environ, "HOME": temp}, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertNotIn("HOST5_SYNTAX\tSHA256", run.stdout)

    def test_rejects_injected_or_inconsistent_diagnostic(self):
        lines = [
            "HOST5_SYNTAX\tSHA256\t" + "a" * 64,
            "HOST5_SYNTAX\tSTATUS\tOK",
            "HOST5_SYNTAX\tCATEGORY\tNONE",
            "HOST5_SYNTAX\tLINE\t0",
            "HOST5_SYNTAX\tNORMALIZED_OK\t1",
        ]
        good = "\n".join(lines) + "\n"
        self.assertEqual(audit.parse_remote_output(good)["STATUS"], "OK")
        bad = [
            good + "OTHER SOURCE CODE\n",
            good + lines[2] + "\n",
            good.replace(lines[0], lines[0] + ";ls"),
            good.replace("HOST5_SYNTAX\tSTATUS\tOK", "HOST5_SYNTAX\tSTATUS\tINVALID"),
            good.replace("HOST5_SYNTAX\tLINE\t0", "HOST5_SYNTAX\tLINE\t../../"),
            good.replace("HOST5_SYNTAX\tNORMALIZED_OK\t1", ""),
        ]
        for payload in bad:
            with self.subTest(payload=payload[-50:]):
                with self.assertRaises(audit.Blocked):
                    audit.parse_remote_output(payload)

    def test_remote_logic_is_syntax_only_not_execution_or_mutation(self):
        self.assertIn('bash -n -- "$script"', audit.REMOTE)
        self.assertIn("sha256sum", audit.REMOTE)
        self.assertNotIn("source \"$script\"", audit.REMOTE)
        self.assertNotIn("bash \"$script\"", audit.REMOTE)
        self.assertNotIn("mv \"$script\"", audit.REMOTE)
        self.assertNotIn("rm \"$script\"", audit.REMOTE)
        self.assertNotIn("cat \"$script\"", audit.REMOTE)


if __name__ == "__main__":
    unittest.main()
