import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hostinger", ROOT / "scripts" / "hostinger.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ACCOUNT = {"host": "123.123.123.123", "user": "u123456789", "port": 65002}
SITE = {"domain": "example.com", "type": "theme", "slug": "demo-theme",
        "health_url": "https://example.com/"}


def cfg(site=None, include_site=True):
    sites = {"demo": site if site is not None else SITE} if include_site else {}
    return {"version": 2, "account": dict(ACCOUNT), "sites": sites}


class ConfigTests(unittest.TestCase):
    def test_valid_example(self):
        data = json.loads((ROOT / "config/sites.example.json").read_text())
        self.assertEqual(len(m.validate_config(data)["sites"]), 1)

    def test_one_account_without_registered_sites(self):
        result = m.validate_config(cfg(include_site=False))
        self.assertEqual(result["sites"], {})

    def test_account_hostname_rejects_injection(self):
        bad = cfg()
        bad["account"]["host"] = "81.16.31.38;uname"
        self.assertRaises(m.Blocked, m.validate_config, bad)

    def test_account_user_rejects_shell(self):
        bad = cfg()
        bad["account"]["user"] = "u123;echo"
        self.assertRaises(m.Blocked, m.validate_config, bad)

    def test_port_requires_integer(self):
        bad = cfg()
        bad["account"]["port"] = True
        self.assertRaises(m.Blocked, m.validate_config, bad)

    def test_rejects_deployment_destination_override(self):
        self.assertRaises(m.Blocked, m.validate_config, cfg({**SITE, "destination": "/etc"}))

    def test_bad_domain(self):
        for domain in ("../etc", "example.com/other", "-bad.com", "a..b.com"):
            with self.subTest(domain=domain):
                self.assertRaises(m.Blocked, m.validate_config, cfg({**SITE, "domain": domain}))

    def test_rejects_host_on_single_site(self):
        self.assertRaises(m.Blocked, m.validate_config,
                          cfg({**SITE, "host": "server.example.com"}))

    def test_type_restricted(self):
        self.assertRaises(m.Blocked, m.validate_config, cfg({**SITE, "type": "root"}))

    def test_health_origin_restricted(self):
        self.assertRaises(m.Blocked, m.validate_config,
                          cfg({**SITE, "health_url": "https://other.com/"}))

    def test_account_scoped_destination(self):
        self.assertEqual(m.destination(SITE, ACCOUNT),
                         "/home/u123456789/domains/example.com/public_html/"
                         "wp-content/themes/demo-theme")
        self.assertIn("/plugins/", m.destination({**SITE, "type": "plugin"}, ACCOUNT))


class HostingBindingTests(unittest.TestCase):
    def test_all_seven_observed_environment_bindings_are_unique(self):
        pins = m.HOSTING_ACCOUNT_FINGERPRINTS
        self.assertEqual(set(pins), {f"hostinger-{i}" for i in range(1, 8)})
        self.assertEqual(len(set(pins.values())), 7)

    def test_selected_account_is_checked_before_ssh_or_secret_use(self):
        original = cfg(include_site=False)
        fp = m.account_fingerprint(original)
        with patch.dict(m.HOSTING_ACCOUNT_FINGERPRINTS, {"hostinger-5": fp}):
            with patch.dict(os.environ, {"HOSTING_ENV": "hostinger-5"}):
                with patch.object(m, "verify_account") as ssh_call:
                    with self.assertRaises(m.Blocked):
                        swapped = cfg(include_site=False)
                        swapped["account"]["user"] = "u987654321"
                        m.execute("connect", "", "", swapped)
                    ssh_call.assert_not_called()

    def test_wrong_environment_and_unverified_number_fail_closed(self):
        with self.assertRaises(m.Blocked):
            m.verify_hosting_binding(cfg(include_site=False), "hostinger-8")
        with self.assertRaises(m.Blocked):
            m.verify_hosting_binding(cfg(include_site=False), "hostinger-7")

    def test_correct_binding_preserves_readonly_connect(self):
        config = cfg(include_site=False)
        expected = m.account_fingerprint(config)
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\\ntest\\n-----END OPENSSH PRIVATE KEY-----"
        with patch.dict(m.HOSTING_ACCOUNT_FINGERPRINTS, {"hostinger-5": expected}):
            with patch.dict(os.environ, {
                "HOSTING_ENV": "hostinger-5",
                "HOSTINGER_SSH_PRIVATE_KEY": key,
                "HOSTINGER_SSH_KNOWN_HOSTS": "[123.123.123.123]:65002 ssh-ed25519 test",
            }):
                with patch.object(m, "verify_account") as ssh_call:
                    m.execute("connect", "", "", config)
                    ssh_call.assert_called_once()

    def test_workflow_passes_selected_environment_to_guard(self):
        workflow = (ROOT / ".github/workflows/hostinger.yml").read_text()
        self.assertIn("HOSTING_ENV: " + chr(36) + "{{ inputs.hosting }}", workflow)
        self.assertNotIn("StrictHostKeyChecking=no", workflow)


class PayloadTests(unittest.TestCase):
    def make(self, files):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        location = root / "payload" / "demo"
        location.mkdir(parents=True)
        for name, body in files.items():
            output = location / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(body)
        return directory, root

    def test_acceptable_theme(self):
        tmp, root = self.make({"style.css": "Theme Name: Demo", "index.php": "<?php"})
        with tmp:
            self.assertEqual(m.inspect_payload("demo", SITE, root),
                             root / "payload/demo")

    def test_theme_requires_css(self):
        tmp, root = self.make({"index.php": "<?php"})
        with tmp:
            self.assertRaises(m.Blocked, m.inspect_payload, "demo", SITE, root)

    def test_hidden_file_rejected(self):
        tmp, root = self.make({"style.css": "Theme Name: Demo", ".env": "secret"})
        with tmp:
            self.assertRaises(m.Blocked, m.inspect_payload, "demo", SITE, root)

    def test_wordpress_config_rejected(self):
        tmp, root = self.make({"style.css": "Theme Name: Demo", "wp-config.php": "secret"})
        with tmp:
            self.assertRaises(m.Blocked, m.inspect_payload, "demo", SITE, root)

    def test_plugin_requires_php(self):
        tmp, root = self.make({"readme.txt": "hello"})
        with tmp:
            self.assertRaises(m.Blocked, m.inspect_payload, "demo",
                              {**SITE, "type": "plugin"}, root)

    def test_symlink_rejected(self):
        tmp, root = self.make({"style.css": "Theme Name: Demo"})
        with tmp:
            (root / "payload/demo/link").symlink_to(root)
            self.assertRaises(m.Blocked, m.inspect_payload, "demo", SITE, root)


class AccountTests(unittest.TestCase):
    def test_account_connect_checks_only_readable_domain_root(self):
        with patch.object(m, "command", return_value="") as call:
            m.verify_account(ACCOUNT, ["ssh"])
            sent = call.call_args.args[0][-1]
            self.assertIn('test -r "$HOME/domains"', sent)
            self.assertNotIn("--delete", sent)

    def test_inventory_counts_without_listing_names(self):
        with patch.object(m, "command", return_value=" 8\n"):
            self.assertEqual(m.count_domain_folders(ACCOUNT, ["ssh"]), 8)

    def test_inventory_rejects_unknown_output(self):
        with patch.object(m, "command", return_value="site.nl"):
            self.assertRaises(m.Blocked, m.count_domain_folders, ACCOUNT, ["ssh"])

    def test_hostwide_connect_needs_no_sites(self):
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"
        secrets = {"HOSTINGER_SSH_PRIVATE_KEY": key,
                   "HOSTINGER_SSH_KNOWN_HOSTS": "[123.123.123.123]:65002 ssh-ed25519 test"}
        with patch.dict(os.environ, secrets), patch.object(m, "verify_account") as check:
            m.execute("connect", "", "", cfg(include_site=False))
            check.assert_called_once()

    def test_hostwide_connect_rejects_site_argument(self):
        self.assertRaises(m.Blocked, m.execute,
                          "connect", "demo", "", cfg(include_site=False))

    def test_deploy_requires_site(self):
        self.assertRaises(m.Blocked, m.execute,
                          "deploy", "", "", cfg(include_site=False))

    def test_deploy_requires_confirmation(self):
        tmp, root = PayloadTests().make({"style.css": "Theme Name: Demo"})
        with tmp:
            self.assertRaises(m.Blocked, m.execute,
                              "deploy", "demo", "", cfg(), root)

    def test_rsync_has_no_delete(self):
        with patch.object(m, "command", return_value="") as call:
            m.synchronize(SITE, ACCOUNT, Path("/tmp"), ["ssh"], dry_run=False)
            args = call.call_args.args[0]
            self.assertNotIn("--delete", args)
            self.assertIn("--delay-updates", args)

    def test_preview_does_not_write(self):
        with patch.object(m, "command", return_value="") as call:
            m.synchronize(SITE, ACCOUNT, Path("/tmp"), ["ssh"], dry_run=True)
            self.assertIn("--dry-run", call.call_args.args[0])


class WorkflowEnvironmentTests(unittest.TestCase):
    def test_first_hosting_environment_is_explicit(self):
        text = (ROOT / '.github/workflows/hostinger.yml').read_text()
        self.assertIn('default: hostinger-1', text)
        self.assertIn('name: ' + chr(36) + '{{ inputs.hosting }}', text)

    def test_hosting_environments_are_allowlisted(self):
        text = (ROOT / '.github/workflows/hostinger.yml').read_text()
        expected = 'options: [' + ', '.join('hostinger-' + str(i) for i in range(1, 11)) + ']'
        self.assertIn(expected, text)
        self.assertNotIn('options: [hostinger, ', text)

    def test_manual_only_and_secret_boundaries(self):
        text = (ROOT / '.github/workflows/hostinger.yml').read_text()
        self.assertIn('workflow_dispatch:', text)
        self.assertNotIn('schedule:', text)
        self.assertIn("if: github.ref == 'refs/heads/main'", text)
        for name in ('HOSTINGER_SITES_JSON', 'HOSTINGER_SSH_PRIVATE_KEY', 'HOSTINGER_SSH_KNOWN_HOSTS'):
            self.assertIn('secrets.' + name, text)

if __name__ == "__main__":
    unittest.main()
