import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "wordpress_maintenance", ROOT / "scripts" / "wordpress_maintenance.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ACCOUNT = {"host": "123.123.123.123", "user": "u123456789", "port": 65002}
CFG = {"version": 2, "account": ACCOUNT, "sites": {}}
DIGEST = "a" * 64
PREFLIGHT = f"MAINT\tSCRIPT_SHA256\t{DIGEST}\nMAINT\tWORDPRESS_COUNT\t1\nMAINT\tPRECHECK\tOK\n"
UPDATE = (f"MAINT\tSCRIPT_SHA256\t{DIGEST}\nMAINT\tWORDPRESS_COUNT\t1\n"
          "MAINT\tUPDATE_EXIT\t0\nMAINT\tWORDPRESS_AFTER\t1\n"
          "MAINT\tSITE\texample.com\nMAINT\tCACHE_OK\t1\nMAINT\tCACHE_FAILED\t0\n"
          "MAINT\tWP_OK\t1\nMAINT\tWP_FAILED\t0\n")


class GuardTests(unittest.TestCase):
    def test_confirmation_and_actions(self):
        for value in ("", "UPDATE:hostinger-2:ALL", "UPDATE:hostinger-1:ALL "):
            with self.assertRaises(m.Blocked):
                m.validate_request("update", value, CFG)
        self.assertEqual(m.validate_request("update", m.CONFIRMATION, CFG)["sites"], {})
        self.assertEqual(m.validate_request("preflight", "", CFG)["sites"], {})
        for action, confirm in (("preflight", m.CONFIRMATION),
                                ("deploy", m.CONFIRMATION)):
            with self.assertRaises(m.Blocked):
                m.validate_request(action, confirm, CFG)

    def test_remote_response_rejects_injection_and_duplicates(self):
        self.assertEqual(m.parse_remote_output(PREFLIGHT)["WORDPRESS_COUNT"], 1)
        bad = ("uncontrolled\n" + PREFLIGHT,
               PREFLIGHT + "MAINT\tSITE\t../.ssh\n",
               PREFLIGHT + "MAINT\tWORDPRESS_COUNT\t2\n",
               PREFLIGHT + "MAINT\tSITE\texample.com\nMAINT\tSITE\texample.com\n",
               "MAINT\tSCRIPT_SHA256\tINVALID\nMAINT\tWORDPRESS_COUNT\t1\n")
        for case in bad:
            with self.subTest(value=case[:30]):
                with self.assertRaises(m.Blocked):
                    m.parse_remote_output(case)

    def test_secret_domain_does_not_appear_in_log(self):
        with patch.object(m, "public_healthcheck", return_value=True):
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertTrue(m.evaluate("update", m.parse_remote_output(UPDATE), 0))
        self.assertNotIn("example.com", printed.getvalue())

    def test_partial_update_never_returns_success(self):
        good = m.parse_remote_output(UPDATE)
        with patch.object(m, "public_healthcheck", return_value=True):
            for key, value in (("UPDATE_EXIT", 2), ("CACHE_FAILED", 1),
                               ("WP_FAILED", 1)):
                with self.subTest(key=key):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertFalse(m.evaluate("update", {**good, key: value}, 0))
            with self.assertRaises(m.Blocked):
                m.evaluate("update", {**good, "WORDPRESS_AFTER": 2}, 0)

    def test_http_fatal_error_and_redirect_block(self):
        class FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_a): return False
            def read(self, _n): return b"Fatal error: database connection"
        class FakeOpener:
            def open(self, *_a, **_kw): return FakeResp()
        with patch.object(m.request, "build_opener", return_value=FakeOpener()):
            self.assertFalse(m.public_healthcheck("example.com"))
        with self.assertRaises(m.Blocked):
            m.SameDomainRedirect("example.com").redirect_request(
                None, None, 302, "", {}, "https://another.example/")


class RemoteShellTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.root = self.home / "domains"
        self.root.mkdir()
        self.updater = self.root / "update_wordpress.sh"
        self.updater.write_text('''#!/usr/bin/env bash\nprintf 'UPDATED\\n' >> "$TRACE"\necho 'PRIVATE OUTPUT'\nexit "${UPDATE_RC:-0}"\n''')
        site = self.root / "example.com/public_html"
        (site / "wp-includes").mkdir(parents=True)
        (site / "wp-load.php").touch()
        (site / "wp-includes/version.php").touch()
        bindir = self.home / "bin"
        bindir.mkdir()
        wp = bindir / "wp"
        wp.write_text('''#!/usr/bin/env bash\nprintf 'WP %s\\n' "$*" >> "$TRACE"\nif [[ "$*" == *"plugin is-active"* ]]; then exit 1; fi\nif [[ "$*" == *"cache flush"* && "${CACHE_FAIL:-0}" == "1" ]]; then exit 1; fi\nexit 0\n''')
        wp.chmod(0o755)
        self.trace = self.home / "calls.txt"
        self.env = {**os.environ, "HOME": str(self.home), "TRACE": str(self.trace),
                    "PATH": str(bindir) + ":" + os.environ["PATH"]}
        self.shell = (ROOT / "scripts/wordpress_maintenance_remote.sh").read_text()

    def run_shell(self, action, **kw):
        return subprocess.run(["bash", "-s", "--", action], input=self.shell,
                              text=True, capture_output=True,
                              env={**self.env, **kw}, timeout=30)

    def test_preflight_does_not_mutate(self):
        result = self.run_shell("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MAINT\tPRECHECK\tOK", result.stdout)
        self.assertFalse(self.trace.exists())
        self.assertFalse((self.home / ".wordpress-maintenance-logs").exists())

    def test_update_then_cache_then_health(self):
        result = self.run_shell("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.trace.read_text()
        self.assertLess(calls.index("UPDATED"), calls.index("cache flush"))
        self.assertLess(calls.index("cache flush"), calls.index("core is-installed"))
        self.assertIn("MAINT\tWP_OK\t1", result.stdout)
        self.assertNotIn("PRIVATE OUTPUT", result.stdout)
        logfile = next((self.home / ".wordpress-maintenance-logs").glob("update-*.log"))
        self.assertIn("PRIVATE OUTPUT", logfile.read_text())
        self.assertEqual(logfile.stat().st_mode & 0o777, 0o600)

    def test_nonzero_updater_still_runs_checks(self):
        result = self.run_shell("update", UPDATE_RC="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MAINT\tUPDATE_EXIT\t2", result.stdout)
        self.assertIn("MAINT\tCACHE_OK\t1", result.stdout)
        self.assertIn("MAINT\tWP_OK\t1", result.stdout)

    def test_cache_failure_is_failure(self):
        result = self.run_shell("update", CACHE_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MAINT\tCACHE_FAILED\t1", result.stdout)

    def test_unknown_action_and_missing_script_fail(self):
        self.assertNotEqual(self.run_shell("deploy").returncode, 0)
        self.updater.unlink()
        self.assertNotEqual(self.run_shell("preflight").returncode, 0)
        self.updater.symlink_to("/etc/passwd")
        self.assertNotEqual(self.run_shell("preflight").returncode, 0)


class WorkflowTests(unittest.TestCase):
    def test_manual_only_one_environment(self):
        text = (ROOT / ".github/workflows/wordpress-onderhoud-hostinger-1.yml").read_text()
        for exact in ("workflow_dispatch:", "name: hostinger-1",
                      "group: hostinger-ssh-operations",
                      "if: github.ref == 'refs/heads/main'",
                      "permissions:\n  contents: read"):
            self.assertIn(exact, text)
        for forbidden in ("  schedule:", "  push:", "inputs.hosting"):
            self.assertNotIn(forbidden, text)
        for secret in ("HOSTINGER_SITES_JSON", "HOSTINGER_SSH_PRIVATE_KEY",
                       "HOSTINGER_SSH_KNOWN_HOSTS"):
            self.assertIn("secrets." + secret, text)

    def test_existing_transport_modes_unchanged(self):
        text = (ROOT / ".github/workflows/hostinger.yml").read_text()
        self.assertIn("options: [connect, list, preview, deploy]", text)
        self.assertNotIn("UPDATE:hostinger-1:ALL", text)


if __name__ == "__main__":
    unittest.main()
