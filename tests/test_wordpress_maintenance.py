"""Fail-closed unit and isolated shell regressions. No real SSH or production sites."""
import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("wordpress_maintenance", ROOT / "scripts/wordpress_maintenance.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ACCOUNT = {"host": "123.123.123.123", "user": "u123456789", "port": 65002}
CONFIG = {"version": 2, "account": ACCOUNT, "sites": {}}
DIGEST = "a" * 64
INV_DIGEST = "b" * 64
DIAG_FIELDS = "".join(f"MAINT\t{key}\t0\n" for key in m.DIAG_REASONS)
DIAG_FIELDS_AFTER = "".join(f"MAINT\t{key}_AFTER\t0\n" for key in m.DIAG_REASONS)
PREFLIGHT = (f"MAINT\tSCRIPT_SHA256\t{DIGEST}\nMAINT\tINVENTORY_SHA256\t{INV_DIGEST}\n"
             "MAINT\tWORDPRESS_COUNT\t1\nMAINT\tUNSUPPORTED_COUNT\t0\n"
             "MAINT\tMULTISITE_COUNT\t0\n" + DIAG_FIELDS + "MAINT\tPRECHECK\tOK\n")
UPDATE = (PREFLIGHT + "MAINT\tUPDATE_EXIT\t0\nMAINT\tWORDPRESS_AFTER\t1\n"
          "MAINT\tSITE\texample.com\nMAINT\tERROR_SIGNATURES\t0\n"
          "MAINT\tUNSUPPORTED_AFTER\t0\nMAINT\tMULTISITE_AFTER\t0\n" + DIAG_FIELDS_AFTER +
          "MAINT\tCACHE_OK\t1\nMAINT\tCACHE_FAILED\t0\nMAINT\tWP_OK\t1\n"
          "MAINT\tWP_FAILED\t0\nMAINT\tCHECK_FAILED\t0\n"
          f"MAINT\tPENDING_UPDATES\t0\nMAINT\tINVENTORY_AFTER_SHA256\t{INV_DIGEST}\n")


class RequestGuards(unittest.TestCase):
    def test_typed_confirmation_and_two_pins(self):
        for confirm, a, b in (("", DIGEST, INV_DIGEST),
                              ("UPDATE:hostinger-2:ALL", DIGEST, INV_DIGEST),
                              (m.CONFIRMATION, "invalid", INV_DIGEST),
                              (m.CONFIRMATION, DIGEST, "invalid"),
                              (m.CONFIRMATION + " ", DIGEST, INV_DIGEST)):
            with self.subTest(confirm=confirm, script=a, inventory=b):
                with self.assertRaises(m.Blocked):
                    m.validate_request("update", confirm, CONFIG, a, b)
        self.assertEqual(m.validate_request("update", m.CONFIRMATION, CONFIG, DIGEST, INV_DIGEST)["sites"], {})
        self.assertEqual(m.validate_request("preflight", "", CONFIG)["sites"], {})

    def test_preflight_rejects_mutation_arguments(self):
        for a, c, d in (("", DIGEST, ""), (m.CONFIRMATION, "", ""),
                        ("", "", INV_DIGEST)):
            with self.assertRaises(m.Blocked):
                m.validate_request("preflight", a, CONFIG, c, d)
        with self.assertRaises(m.Blocked):
            m.validate_request("deploy", m.CONFIRMATION, CONFIG, DIGEST, INV_DIGEST)

    def test_parser_requires_all_tags_and_rejects_injection(self):
        self.assertEqual(m.parse_remote_output(PREFLIGHT)["INVENTORY_SHA256"], INV_DIGEST)
        for bad in ("garbage\n" + PREFLIGHT,
                    PREFLIGHT.replace("\tOK", "\tUNSAFE"),
                    PREFLIGHT + "MAINT\tSITE\t../../etc\n",
                    PREFLIGHT + "MAINT\tWORDPRESS_COUNT\t2\n",
                    PREFLIGHT + "MAINT\tSITE\texample.com\nMAINT\tSITE\texample.com\n",
                    PREFLIGHT.replace(DIGEST, "nope"),
                    PREFLIGHT.replace("MAINT\tINVENTORY_SHA256\t", "MAINT\tMISSING\t"),
                    PREFLIGHT + "MAINT\tERROR_SIGNATURES\tno\n"):
            with self.subTest(bad=bad[:50]):
                with self.assertRaises(m.Blocked):
                    m.parse_remote_output(bad)

    def test_preflight_requires_clean_scope(self):
        for field in ("UNSUPPORTED_COUNT", "MULTISITE_COUNT"):
            result = m.parse_remote_output(PREFLIGHT)
            result[field] = 1
            with self.subTest(field=field):
                with self.assertRaises(m.Blocked):
                    m.evaluate("preflight", result, 0)

    def test_success_does_not_leak_private_domain(self):
        with patch.object(m, "public_healthcheck", return_value=True):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(m.evaluate("update", m.parse_remote_output(UPDATE), 0, DIGEST, INV_DIGEST))
        self.assertNotIn("example.com", output.getvalue())
        self.assertIn("1/1", output.getvalue())

    def test_failure_paths_are_never_green(self):
        clean = m.parse_remote_output(UPDATE)
        with patch.object(m, "public_healthcheck", return_value=True):
            for overrides in ({"UPDATE_EXIT": 2}, {"ERROR_SIGNATURES": 1},
                              {"CACHE_FAILED": 1}, {"WP_FAILED": 1},
                              {"CHECK_FAILED": 1}, {"PENDING_UPDATES": 1},
                              {"INVENTORY_AFTER_SHA256": "c" * 64},
                              {"UNSUPPORTED_AFTER": 1, "DIAG_HOME_MISMATCH_AFTER": 1}, {"MULTISITE_AFTER": 1}):
                with self.subTest(overrides=overrides), contextlib.redirect_stdout(io.StringIO()):
                    self.assertFalse(m.evaluate("update", {**clean, **overrides}, 0, DIGEST, INV_DIGEST))
            with self.assertRaises(m.Blocked):
                m.evaluate("update", clean, 0, "c" * 64, INV_DIGEST)
            with self.assertRaises(m.Blocked):
                m.evaluate("update", clean, 0, DIGEST, "c" * 64)
            with self.assertRaises(m.Blocked):
                m.evaluate("update", {**clean, "WORDPRESS_AFTER": 2}, 0, DIGEST, INV_DIGEST)

    def test_preflight_ssh_command_has_no_placeholder_arguments(self):
        class FakeDone:
            returncode = 0
            stdout = PREFLIGHT
            stderr = ""
        with patch.object(m.subprocess, "run", return_value=FakeDone()) as runner:
            result, rc = m.run_remote(["ssh"], ACCOUNT, "preflight")
        self.assertEqual(rc, 0)
        self.assertEqual(result["PRECHECK"], "OK")
        self.assertEqual(runner.call_args.args[0][-1], "bash -s -- preflight")
        with patch.object(m.subprocess, "run", return_value=FakeDone()) as runner:
            m.run_remote(["ssh"], ACCOUNT, "update", DIGEST, INV_DIGEST)
        self.assertEqual(runner.call_args.args[0][-1], f"bash -s -- update {DIGEST} {INV_DIGEST}")

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
                None, None, 302, "", {}, "https://evil.example/")


class RemoteShellTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.domains = self.home / "domains"
        self.domains.mkdir()
        self.script = self.domains / "update_wordpress.sh"
        self.set_updater('''#!/usr/bin/env bash
printf 'UPDATED\n' >> "$MAINT_TRACE"
echo 'private updater output'
exit "${UPDATE_RC:-0}"
''')
        self.site = self.mk_site('example.com')
        self.bin = self.home / "bin"
        self.bin.mkdir()
        wp = self.bin / "wp"
        wp.write_text('''#!/usr/bin/env bash
printf 'WP: %s\n' "$*" >> "$MAINT_TRACE"
if [[ "$*" == *"core is-installed"* && "${CORE_FAIL:-0}" == "1" ]]; then exit 7; fi
if [[ "$*" == *"--network"* ]]; then [[ "${IS_MULTISITE:-0}" == "1" || -f "$HOME/turn_on_multisite" ]]; exit $?; fi
if [[ "$*" == *"option get home"* ]]; then
  if [[ "${HOME_READ_FAIL:-0}" == "1" ]]; then exit 7; fi
  if [[ "${HOME_MISMATCH:-0}" == "1" ]]; then echo "https://unrelated.example"; exit 0; fi
  mypath="${1#--path=}"
  mydomain="${mypath%/public_html}"
  echo "https://${mydomain##*/}"
  exit 0
fi
if [[ "$*" == *"plugin is-active litespeed-cache"* ]]; then [[ "${LS_ACTIVE:-0}" == "1" ]]; exit $?; fi
if [[ "$*" == *"plugin is-active wp-rocket"* ]]; then [[ "${ROCKET_ACTIVE:-0}" == "1" ]]; exit $?; fi
if [[ "$*" == *"cache flush"* && "${CACHE_FAIL:-0}" == "1" ]]; then exit 1; fi
if [[ "$*" == *"litespeed-purge"* && "${LS_FAIL:-0}" == "1" ]]; then exit 1; fi
if [[ "$*" == *"--format=count"* ]]; then
  if [[ "${COUNT_FAIL:-0}" == "1" ]]; then echo UNKNOWN; exit 0; fi
  if [[ "${PENDING:-0}" == "1" ]]; then echo 1; else echo 0; fi
  exit 0
fi
if [[ "$*" == *"db_version"* && "${DB_FAIL:-0}" == "1" ]]; then exit 9; fi
exit 0
''')
        wp.chmod(0o755)
        self.trace = self.home / "trace.txt"
        self.env = {**os.environ, "HOME": str(self.home),
                    "MAINT_TRACE": str(self.trace), "PATH": str(self.bin) + ":" + os.environ["PATH"]}
        self.remote = (ROOT / "scripts/wordpress_maintenance_remote.sh").read_text()

    def set_updater(self, body):
        self.script.write_text(body)

    def mk_site(self, domain, subpath="public_html"):
        site = self.domains / domain / subpath
        (site / "wp-includes").mkdir(parents=True, exist_ok=True)
        (site / "wp-load.php").touch()
        (site / "wp-includes/version.php").touch()
        return site

    def shell(self, *args, **extra):
        return subprocess.run(["bash", "-s", "--", *args], input=self.remote,
                              text=True, capture_output=True,
                              env={**self.env, **extra}, timeout=30)

    def preflight(self, **extra):
        r = self.shell("preflight", **extra)
        vals = {line.split("\t")[1]:line.split("\t")[2] for line in r.stdout.splitlines() if line.startswith("MAINT\t")}
        return r, vals

    def update(self, *, pins=None, **extra):
        if pins is None:
            pre, pins = self.preflight(**extra)
            self.assertEqual(pre.returncode, 0, pre.stderr + pre.stdout)
        return self.shell("update", pins["SCRIPT_SHA256"], pins["INVENTORY_SHA256"], **extra)

    def test_preflight_readonly_and_pins(self):
        r, data = self.preflight()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(data["SCRIPT_SHA256"], r"^[0-9a-f]{64}$")
        self.assertRegex(data["INVENTORY_SHA256"], r"^[0-9a-f]{64}$")
        self.assertIn("MAINT\tPRECHECK\tOK", r.stdout)
        self.assertFalse(self.trace.exists() and "UPDATED" in self.trace.read_text())
        self.assertFalse((self.home / ".wordpress-maintenance-logs").exists())

    def test_success_update_cache_checks_and_private_log(self):
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        calls = self.trace.read_text()
        self.assertLess(calls.index("UPDATED"), calls.index("cache flush"))
        self.assertLess(calls.index("cache flush"), calls.index("core check-update"))
        self.assertIn("MAINT\tPENDING_UPDATES\t0", r.stdout)
        self.assertIn("MAINT\tCHECK_FAILED\t0", r.stdout)
        self.assertNotIn("private updater output", r.stdout)
        logs = list((self.home / ".wordpress-maintenance-logs").glob("update-*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("private updater output", logs[0].read_text())
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)

    def test_update_failure_still_does_postchecks(self):
        r = self.update(UPDATE_RC="2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tUPDATE_EXIT\t2", r.stdout)
        self.assertIn("MAINT\tWP_OK\t1", r.stdout)

    def test_fatal_error_with_zero_exit_is_detected(self):
        self.set_updater('#!/usr/bin/env bash\necho "Fatal error: plugin update failed"\nexit 0\n')
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tERROR_SIGNATURES\t1", r.stdout)

    def test_harmless_no_errors_sentence_is_accepted(self):
        self.set_updater('#!/usr/bin/env bash\necho "0 errors; all fine"\nexit 0\n')
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_changed_script_hash_is_blocked_without_run(self):
        pre, pins = self.preflight()
        self.assertEqual(pre.returncode, 0)
        self.set_updater('#!/usr/bin/env bash\necho "MALICIOUS CHANGED"\nexit 0\n')
        r = self.update(pins=pins)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tPRECHECK\tMISMATCH", r.stdout)
        self.assertFalse((self.home / ".wordpress-maintenance-logs").exists())

    def test_changed_inventory_same_count_is_blocked(self):
        pre, pins = self.preflight()
        self.assertEqual(pre.returncode, 0)
        (self.domains / "example.com").rename(self.domains / "replacement.com")
        r = self.update(pins=pins)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tPRECHECK\tMISMATCH", r.stdout)

    def test_unrecognised_nested_wordpress_blocks_preflight(self):
        self.mk_site("second.com", "public_html/blog")
        r, info = self.preflight()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tPRECHECK\tBLOCKED", r.stdout)
        self.assertEqual(info["UNSUPPORTED_COUNT"], "1")

    def test_multisite_blocks_preflight(self):
        r, info = self.preflight(IS_MULTISITE="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(info["MULTISITE_COUNT"], "1")

    def test_wordpress_home_mismatch_blocks_preflight(self):
        r, info = self.preflight(HOME_MISMATCH="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(info["UNSUPPORTED_COUNT"], "1")

    def test_new_nested_wordpress_after_update_is_never_green(self):
        self.set_updater('''#!/usr/bin/env bash
mkdir -p "$HOME/domains/extra.com/public_html/blog/wp-includes"
touch "$HOME/domains/extra.com/public_html/blog/wp-load.php" "$HOME/domains/extra.com/public_html/blog/wp-includes/version.php"
exit 0
''')
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tUNSUPPORTED_AFTER\t1", r.stdout)
        self.assertIn("MAINT\tDIAG_NONSTANDARD_AFTER\t1", r.stdout)

    def test_multisite_activated_during_update_is_never_green(self):
        self.set_updater('#!/usr/bin/env bash\ntouch "$HOME/turn_on_multisite"\nexit 0\n')
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tMULTISITE_AFTER\t1", r.stdout)

    def test_anonymized_reason_counts_for_realistic_three_failures(self):
        self.mk_site("backup.example", "public_html/archived")
        partial = self.domains / "partial.example/public_html"
        partial.mkdir(parents=True)
        (partial / "wp-load.php").touch()
        run, info = self.preflight(HOME_MISMATCH="1")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(info["WORDPRESS_COUNT"], "1")
        self.assertEqual(info["UNSUPPORTED_COUNT"], "3")
        self.assertEqual(info["DIAG_NONSTANDARD"], "1")
        self.assertEqual(info["DIAG_INCOMPLETE"], "1")
        self.assertEqual(info["DIAG_HOME_MISMATCH"], "1")
        self.assertIn("MAINT\tPRECHECK\tBLOCKED", run.stdout)
        for private in ("backup.example", "partial.example", "example.com"):
            self.assertNotIn(private, run.stdout)
        parsed = m.parse_remote_output(run.stdout)
        with self.assertRaises(m.Blocked), contextlib.redirect_stdout(io.StringIO()) as printed:
            m.evaluate("preflight", parsed, run.returncode)
        report = printed.getvalue()
        self.assertIn("Afwijkende WordPress-mapstructuur: 1", report)
        self.assertIn("Onvolledige WordPress-bestanden: 1", report)
        self.assertIn("WordPress home-URL wijkt af", report)
        self.assertNotIn("backup.example", report)

    def test_diagnostic_db_and_home_read_failures(self):
        run, info = self.preflight(CORE_FAIL="1")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(info["DIAG_CORE_UNAVAILABLE"], "1")
        self.assertEqual(info["UNSUPPORTED_COUNT"], "1")
        run, info = self.preflight(HOME_READ_FAIL="1")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(info["DIAG_HOME_UNAVAILABLE"], "1")
        self.assertEqual(info["UNSUPPORTED_COUNT"], "1")

    def test_unusual_domain_name_has_its_own_diagnostic(self):
        self.mk_site("broken_domain", "public_html")
        run, info = self.preflight()
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(info["DIAG_INVALID_DOMAIN"], "1")
        self.assertEqual(info["UNSUPPORTED_COUNT"], "1")
        self.assertNotIn("broken_domain", run.stdout)

    def test_symlink_webroot_is_accounted_for(self):
        link = self.domains / "alias.example/public_html"
        link.parent.mkdir()
        link.symlink_to(self.site, target_is_directory=True)
        run, info = self.preflight()
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(info["UNSUPPORTED_COUNT"], "1")
        self.assertEqual(info["DIAG_SYMLINK"], "1")

    def test_large_mixed_inventory_counts_without_names(self):
        for i in range(29):
            self.mk_site(f"site{i}.example", "public_html")
        self.mk_site("nested.example", "public_html/blog")
        partial = self.domains / "partial.example/public_html"
        partial.mkdir(parents=True)
        (partial / "wp-load.php").touch()
        link = self.domains / "alias.example/public_html"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.site, target_is_directory=True)
        run, info = self.preflight()
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(info["WORDPRESS_COUNT"], "30")
        self.assertEqual(info["UNSUPPORTED_COUNT"], "3")
        self.assertEqual(info["DIAG_NONSTANDARD"], "1")
        self.assertEqual(info["DIAG_INCOMPLETE"], "1")
        self.assertEqual(info["DIAG_SYMLINK"], "1")
        self.assertNotIn("site0.example", run.stdout)

    def test_parser_rejects_diagnostic_omissions_and_mismatch(self):
        with self.assertRaises(m.Blocked):
            m.parse_remote_output(PREFLIGHT.replace("MAINT\tDIAG_INCOMPLETE\t0\n", ""))
        parsed = m.parse_remote_output(PREFLIGHT)
        parsed["UNSUPPORTED_COUNT"] = 1
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(m.Blocked):
                m.evaluate("preflight", parsed, 17)

    def test_symlink_script_and_missing_root_block(self):
        self.script.unlink()
        self.assertNotEqual(self.preflight()[0].returncode, 0)
        self.script.symlink_to("/etc/passwd")
        self.assertNotEqual(self.preflight()[0].returncode, 0)

    def test_cache_failure_marks_job_red(self):
        r = self.update(CACHE_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tCACHE_FAILED\t1", r.stdout)
        self.assertIn("MAINT\tCACHE_OK\t0", r.stdout)

    def test_litespeed_failure_is_not_hidden_in_cache_success_count(self):
        r = self.update(LS_ACTIVE="1", LS_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tCACHE_OK\t0", r.stdout)
        self.assertIn("MAINT\tCACHE_FAILED\t1", r.stdout)

    def test_detects_remaining_wpcli_updates(self):
        r = self.update(PENDING="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tPENDING_UPDATES\t6", r.stdout)

    def test_non_numeric_update_check_is_blocked(self):
        r = self.update(COUNT_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tCHECK_FAILED\t6", r.stdout)

    def test_db_version_mismatch_is_blocked(self):
        r = self.update(DB_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MAINT\tCHECK_FAILED\t1", r.stdout)

    def test_arbitrary_action_is_rejected(self):
        r = self.shell("deploy")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.trace.exists())


class ActionTests(unittest.TestCase):
    def test_manual_only_and_scope(self):
        text = (ROOT / ".github/workflows/wordpress-onderhoud-hostinger-1.yml").read_text()
        for fragment in ("workflow_dispatch:", "name: hostinger-1",
                         "group: hostinger-ssh-operations", "--script-sha256",
                         "--inventory-sha256", "if: github.ref == 'refs/heads/main'",
                         "permissions:\n  contents: read"):
            self.assertIn(fragment, text)
        for forbidden in ("  schedule:", "  push:", "inputs.hosting"):
            self.assertNotIn(forbidden, text)
        for secret in ("HOSTINGER_SITES_JSON", "HOSTINGER_SSH_PRIVATE_KEY", "HOSTINGER_SSH_KNOWN_HOSTS"):
            self.assertIn("secrets." + secret, text)

    def test_legacy_transport_unaffected(self):
        text = (ROOT / ".github/workflows/hostinger.yml").read_text()
        self.assertIn("options: [connect, list, preview, deploy]", text)
        self.assertNotIn("UPDATE:hostinger-1:ALL", text)


if __name__ == "__main__":
    unittest.main()
