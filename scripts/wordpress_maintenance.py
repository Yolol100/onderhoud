#!/usr/bin/env python3
"""Handmatig Hostinger-1 WordPress-onderhoud met afgeschermde SSH en readback.

Geen generieke shellinterface, back-upactie of website-deploy. De remote
update wordt alleen door een expliciete GitHub Actions-dispatch gestart.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib import request
from urllib.parse import urlsplit

from hostinger import Blocked, DOMAIN, dns_name_ok, require, ssh_options, validate_config, verify_account

SCRIPT = Path(__file__).with_name("wordpress_maintenance_remote.sh")
CONFIRMATION = "UPDATE:hostinger-1:ALL"
DIAG_REASONS = {
    "DIAG_NONSTANDARD": "Afwijkende WordPress-mapstructuur",
    "DIAG_INVALID_DOMAIN": "Ongeldige of afwijkende domeinmapnaam",
    "DIAG_SYMLINK": "Symbolische link of afwijkend echt pad",
    "DIAG_INCOMPLETE": "Onvolledige WordPress-bestanden",
    "DIAG_CORE_UNAVAILABLE": "WordPress-database of WP-CLI niet bereikbaar",
    "DIAG_HOME_UNAVAILABLE": "WordPress home-URL niet uitleesbaar",
    "DIAG_HOME_MISMATCH": "WordPress home-URL wijkt af van domeinmap",
}

EXPECTED_TAGS = {
    "SCRIPT_SHA256", "WORDPRESS_COUNT", "PRECHECK", "UPDATE_EXIT",
    "INVENTORY_SHA256", "WORDPRESS_AFTER", "SITE", "CACHE_OK", "CACHE_FAILED",
    "WP_OK", "WP_FAILED", "CHECK_FAILED", "PENDING_UPDATES",
    "INVENTORY_AFTER_SHA256", "UNSUPPORTED_COUNT", "MULTISITE_COUNT",
    "ERROR_SIGNATURES", "UNSUPPORTED_AFTER", "MULTISITE_AFTER",
    *DIAG_REASONS, *(key + "_AFTER" for key in DIAG_REASONS),
}
FATAL_MARKERS = (
    b"fatal error:", b"error establishing a database connection",
    b"there has been a critical error", b"briefly unavailable for scheduled maintenance",
)


def validate_request(action: str, confirmation: str, config: dict,
                     expected_script: str = "", expected_inventory: str = "") -> dict:
    require(action in ("preflight", "update"), "Unsupported maintenance action")
    if action == "update":
        require(confirmation == CONFIRMATION,
                "Update requires exact confirmation: UPDATE:hostinger-1:ALL")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_script)),
                "Update requires SHA-256 from approved preflight")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_inventory)),
                "Update requires inventory SHA-256 from approved preflight")
    else:
        require(not confirmation and not expected_script and not expected_inventory,
                "Preflight must not contain update credentials")
    return validate_config(config)


def parse_remote_output(output: str) -> dict:
    """Only accept machine-readable fields; never print private domains."""
    require(len(output) <= 65536, "Remote response unexpectedly large")
    parsed: dict[str, object] = {"SITE": []}
    for line in output.splitlines():
        parts = line.split("\t")
        require(len(parts) == 3 and parts[0] == "MAINT" and parts[1] in EXPECTED_TAGS,
                "Unexpected output from maintenance script")
        _, key, value = parts
        if key == "SITE":
            require(dns_name_ok(value, DOMAIN), "Unsafe website name from SSH")
            require(value not in parsed["SITE"], "Duplicate website returned by SSH")
            parsed["SITE"].append(value)
            require(len(parsed["SITE"]) <= 250, "Too many websites in result")
        else:
            require(key not in parsed, "Duplicate remote result field")
            if key in ("SCRIPT_SHA256", "INVENTORY_SHA256", "INVENTORY_AFTER_SHA256"):
                require(bool(re.fullmatch(r"[0-9a-f]{64}", value)), "Invalid digest")
            elif key == "PRECHECK":
                require(value in ("OK", "BLOCKED", "MISMATCH"), "Invalid preflight status")
            else:
                require(value.isascii() and value.isdecimal() and len(value) <= 6,
                        "Invalid numeric result")
                value = int(value)
            parsed[key] = value
    require(all(k in parsed for k in ("SCRIPT_SHA256", "INVENTORY_SHA256", "WORDPRESS_COUNT",
                                      "UNSUPPORTED_COUNT", "MULTISITE_COUNT", "PRECHECK",
                                      *DIAG_REASONS)),
            "Missing mandatory preflight results")
    return parsed


def run_remote(ssh: list[str], account: dict, action: str,
               expected_script: str = "", expected_inventory: str = "") -> tuple[dict, int]:
    payload = SCRIPT.read_text(encoding="utf-8")
    remote_command = "bash -s -- preflight" if action == "preflight" else (
        f"bash -s -- update {expected_script} {expected_inventory}")
    remote_args = ssh + [f"{account['user']}@{account['host']}", remote_command]
    try:
        completed = subprocess.run(remote_args, input=payload, text=True,
                                   capture_output=True, check=False, timeout=4300)
    except subprocess.TimeoutExpired as exc:
        raise Blocked("Remote maintenance timed out; status must be checked manually") from exc
    except OSError as exc:
        raise Blocked("SSH executable unavailable") from exc
    if completed.returncode and not completed.stdout:
        raise Blocked(f"Remote preflight/maintenance stopped (exit {completed.returncode})")
    return parse_remote_output(completed.stdout), completed.returncode


class SameDomainRedirect(request.HTTPRedirectHandler):
    def __init__(self, domain: str) -> None:
        super().__init__()
        self.allowed = {domain.lower(), "www." + domain.lower()}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if (url.scheme != "https" or url.hostname not in self.allowed
                or url.port is not None or url.username is not None
                or url.password is not None):
            raise Blocked("Homepage redirects outside its secure domain")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_healthcheck(domain: str) -> bool:
    """Runner-side HTTPS smoke test; no customer URLs in public Actions logs."""
    require(dns_name_ok(domain, DOMAIN), "Invalid domain for public check")
    try:
        opener = request.build_opener(SameDomainRedirect(domain))
        req = request.Request(f"https://{domain}/",
                              headers={"User-Agent": "Webactueel-WordPress-Health/1"})
        with opener.open(req, timeout=20) as page:
            if page.status != 200:
                return False
            body = page.read(65536).lower()
            return bool(body) and not any(marker in body for marker in FATAL_MARKERS)
    except (OSError, ValueError, Blocked):
        return False


def evaluate(action: str, result: dict, ssh_rc: int,
             expected_script: str = "", expected_inventory: str = "") -> bool:
    count = result["WORDPRESS_COUNT"]
    print(f"Bestaand updatescript (SHA-256): {result['SCRIPT_SHA256']}")
    print(f"WordPress-inventaris (SHA-256): {result['INVENTORY_SHA256']}")
    require(isinstance(count, int) and count > 0, "No WordPress sites found")
    print(f"WordPress-installaties gevonden: {count}")
    unsupported = result["UNSUPPORTED_COUNT"]
    multisite = result["MULTISITE_COUNT"]
    print(f"Niet-ondersteunde WordPress-locaties: {unsupported}; multisite-installaties: {multisite}")
    for key, description in DIAG_REASONS.items():
        value = result[key]
        if value:
            print(f"Diagnose: {description}: {value}")
    require(sum(result[key] for key in DIAG_REASONS) == unsupported,
            "Inventory diagnostics incomplete or inconsistent")
    require(unsupported == 0 and multisite == 0, "WordPress-inventory needs manual review")
    require(result["PRECHECK"] == "OK", "Remote preflight mismatch or blocked")
    if action == "preflight":
        require(ssh_rc == 0, "Remote preflight failed")
        print("PREFLIGHT OK: geen update, cacheverwijdering of back-upactie gestart")
        return True

    require(result["SCRIPT_SHA256"] == expected_script and
            result["INVENTORY_SHA256"] == expected_inventory,
            "Update script/inventory changed since approved preflight")
    keys = ("UPDATE_EXIT", "WORDPRESS_AFTER", "CACHE_OK", "CACHE_FAILED",
            "WP_OK", "WP_FAILED", "CHECK_FAILED", "PENDING_UPDATES",
            "ERROR_SIGNATURES", "INVENTORY_AFTER_SHA256", "UNSUPPORTED_AFTER", "MULTISITE_AFTER")
    require(all(key in result for key in (*keys, *(key + "_AFTER" for key in DIAG_REASONS))),
            "Missing mandatory post-update results")
    require(sum(result[key + "_AFTER"] for key in DIAG_REASONS) == result["UNSUPPORTED_AFTER"],
            "Post-update inventory diagnostics incomplete")
    domains = result["SITE"]
    expected = result["WORDPRESS_AFTER"]
    require(expected == len(domains), "Incomplete website inventory after update")
    print(f"Updater afsluitcode: {result['UPDATE_EXIT']}")
    print(f"Na update: {result['WP_OK']}/{expected} WordPress-runtimecontroles geslaagd")
    print(f"Objectcaches geslaagd: {result['CACHE_OK']}/{expected}; cachefouten: {result['CACHE_FAILED']}")
    print(f"Aangetroffen foutmeldingen: {result['ERROR_SIGNATURES']}; WP-CLI-checkfouten: {result['CHECK_FAILED']}")
    print(f"Resterende door WP-CLI detecteerbare updates: {result['PENDING_UPDATES']}")
    print(f"Niet-ondersteunde roots na update: {result['UNSUPPORTED_AFTER']}; multisite: {result['MULTISITE_AFTER']}")
    for key, description in DIAG_REASONS.items():
        if result[key + "_AFTER"]:
            print(f"Nacheckdiagnose: {description}: {result[key + '_AFTER']}")
    print("Extra plugin-cache: LiteSpeed en WP Rocket, indien actief; fouten tellen mee")
    print("Hostinger server-/CDN-cache: afhankelijk van bestaande updater; niet apart geverifieerd")
    with ThreadPoolExecutor(max_workers=6) as pool:
        checks = list(pool.map(public_healthcheck, domains))
    good = sum(checks)
    print(f"Publieke HTTPS-homepages: {good}/{len(domains)} geslaagd")
    for i, ok in enumerate(checks, 1):
        if not ok:
            print(f"Homepagecontrole {i}: MISLUKT (naam verborgen in publieke logs)")
    full = (ssh_rc == 0 and result["UPDATE_EXIT"] == 0 and expected == count
            and result["WP_OK"] == expected and result["WP_FAILED"] == 0
            and result["CACHE_OK"] == expected and result["CACHE_FAILED"] == 0
            and result["ERROR_SIGNATURES"] == 0 and result["CHECK_FAILED"] == 0
            and result["PENDING_UPDATES"] == 0
            and result["UNSUPPORTED_AFTER"] == 0 and result["MULTISITE_AFTER"] == 0
            and result["INVENTORY_AFTER_SHA256"] == expected_inventory
            and good == len(domains) and expected > 0)
    print("RESULTAAT: GESLAAGD" if full else "RESULTAAT: NIET VOLLEDIG - bekijk privé-serverlog")
    return full


def execute(action: str, confirmation: str, config: dict,
            expected_script: str = "", expected_inventory: str = "") -> int:
    config = validate_request(action, confirmation, config, expected_script, expected_inventory)
    key = os.environ.get("HOSTINGER_SSH_PRIVATE_KEY", "")
    hosts = os.environ.get("HOSTINGER_SSH_KNOWN_HOSTS", "")
    require(key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
            and key.rstrip().endswith("-----END OPENSSH PRIVATE KEY-----"),
            "Missing/invalid HOSTINGER_SSH_PRIVATE_KEY")
    require(hosts.strip() and any(t in hosts for t in
            ("ssh-ed25519", "ecdsa-sha2-", "ssh-rsa")),
            "Missing verified HOSTINGER_SSH_KNOWN_HOSTS")
    with tempfile.TemporaryDirectory(prefix="hostinger-wp-") as tmp:
        directory = Path(tmp)
        os.chmod(directory, 0o700)
        key_path, hosts_path = directory / "key", directory / "known_hosts"
        key_path.write_text(key.rstrip("\n") + "\n", encoding="utf-8")
        hosts_path.write_text(hosts.rstrip("\n") + "\n", encoding="utf-8")
        os.chmod(key_path, 0o600)
        os.chmod(hosts_path, 0o600)
        account = config["account"]
        ssh = ssh_options(account, key_path, hosts_path)
        ssh += ["-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4"]
        verify_account(account, ssh)
        result, rc = run_remote(ssh, account, action, expected_script, expected_inventory)
    return 0 if evaluate(action, result, rc, expected_script, expected_inventory) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual Hostinger-1 WordPress maintenance")
    parser.add_argument("action", choices=("preflight", "update"))
    parser.add_argument("--confirm", default="")
    parser.add_argument("--script-sha256", default="")
    parser.add_argument("--inventory-sha256", default="")
    args = parser.parse_args()
    try:
        raw = os.environ.get("HOSTINGER_SITES_JSON", "")
        require(bool(raw.strip()), "Missing HOSTINGER_SITES_JSON")
        return execute(args.action, args.confirm, json.loads(raw),
                       args.script_sha256, args.inventory_sha256)
    except (Blocked, ValueError, TypeError, OSError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
