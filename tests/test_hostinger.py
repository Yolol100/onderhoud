import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hostinger", ROOT / "scripts" / "hostinger.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SITE = {"host":"123.123.123.123","user":"u123456789","port":65002,
        "domain":"example.com","type":"theme","slug":"demo-theme",
        "health_url":"https://example.com/"}


def cfg(site=None):
    return {"version":1, "sites":{"demo":site if site is not None else SITE}}


class ConfigTests(unittest.TestCase):
    def test_valid_example(self):
        data = json.loads((ROOT / "config/sites.example.json").read_text())
        self.assertEqual(len(m.validate_config(data)), 1)

    def test_empty_registry_is_safe(self):
        self.assertEqual(m.validate_config({"version":1,"sites":{}}), {})

    def test_unknown_configuration_field(self):
        self.assertRaises(m.Blocked, m.validate_config,
                          cfg({**SITE,"destination":"/tmp"}))

    def test_bad_domain_and_ssh_host(self):
        for field, value in (("domain","../etc"),("domain","-bad.com"),
                             ("domain","a..b.com"),("host","host;rm -rf /")):
            with self.subTest(field=field,value=value):
                self.assertRaises(m.Blocked,m.validate_config,
                                  cfg({**SITE,field:value}))

    def test_port_type_guard(self):
        self.assertRaises(m.Blocked,m.validate_config,cfg({**SITE,"port":True}))

    def test_type_restricted(self):
        self.assertRaises(m.Blocked,m.validate_config,cfg({**SITE,"type":"root"}))

    def test_health_origin_restricted(self):
        self.assertRaises(m.Blocked,m.validate_config,
                          cfg({**SITE,"health_url":"https://evil.test/"}))

    def test_path_is_exact_wp_theme_directory(self):
        self.assertEqual(m.destination(SITE),
                         "/home/u123456789/domains/example.com/public_html/"
                         "wp-content/themes/demo-theme")
        self.assertIn("/plugins/",m.destination({**SITE,"type":"plugin"}))


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
        return directory,root

    def test_acceptable_theme(self):
        tmp,root = self.make({"style.css":"Theme Name: Demo","index.php":"<?php"})
        with tmp:
            self.assertEqual(m.inspect_payload("demo",SITE,root),
                             root / "payload/demo")

    def test_theme_requires_css(self):
        tmp,root = self.make({"index.php":"<?php"})
        with tmp:
            self.assertRaises(m.Blocked,m.inspect_payload,"demo",SITE,root)

    def test_hidden_file_rejected(self):
        tmp,root = self.make({"style.css":"Theme Name: Demo",".env":"secret"})
        with tmp:
            self.assertRaises(m.Blocked,m.inspect_payload,"demo",SITE,root)

    def test_wordpress_config_rejected(self):
        tmp,root = self.make({"style.css":"Theme Name: Demo","wp-config.php":"secret"})
        with tmp:
            self.assertRaises(m.Blocked,m.inspect_payload,"demo",SITE,root)

    def test_plugin_requires_php(self):
        tmp,root = self.make({"readme.txt":"hello"})
        with tmp:
            self.assertRaises(m.Blocked,m.inspect_payload,"demo",
                              {**SITE,"type":"plugin"},root)

    def test_symlink_rejected(self):
        tmp,root = self.make({"style.css":"Theme Name: Demo"})
        with tmp:
            (root/"payload/demo/link").symlink_to(root)
            self.assertRaises(m.Blocked,m.inspect_payload,"demo",SITE,root)


class DeploymentTests(unittest.TestCase):
    def test_confirm_required(self):
        tmp,root = PayloadTests().make({"style.css":"Theme Name: Demo"})
        with tmp:
            self.assertRaises(m.Blocked,m.execute,"deploy","demo","",cfg(),root)

    def test_rsync_has_no_delete(self):
        with patch.object(m,"command",return_value="") as call:
            m.synchronize(SITE,Path("/tmp"),["ssh"],dry_run=False)
            args=call.call_args.args[0]
            self.assertNotIn("--delete",args)
            self.assertIn("--delay-updates",args)

    def test_preview_does_not_write(self):
        with patch.object(m,"command",return_value="") as call:
            m.synchronize(SITE,Path("/tmp"),["ssh"],dry_run=True)
            self.assertIn("--dry-run",call.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
