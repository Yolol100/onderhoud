#!/usr/bin/env python3
"""Guarded manual Hostinger SSH/rsync for WordPress themes and plugins.

Never runs maintenance, SQL, WP-CLI batches, backup jobs or arbitrary commands.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from urllib import request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z")
USER = re.compile(r"u[0-9]{4,16}\Z")
DOMAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{2,250}\Z")
BANNED = {".git", ".github", ".ssh", "wp-config.php", "wp-admin",
          "wp-includes", "node_modules", ".htaccess", ".user.ini"}
BANNED_SUFFIXES = {".sql", ".sqlite", ".pem", ".key", ".p12", ".pfx"}
MAX_FILES = 2000
MAX_BYTES = 50 * 1024 * 1024


class Blocked(Exception):
    pass


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise Blocked(msg)


def dns_name_ok(name: object, pattern: re.Pattern) -> bool:
    return (isinstance(name, str) and bool(pattern.fullmatch(name))
            and "." in name and ".." not in name
            and all(label and not label.startswith("-") and not label.endswith("-")
                    for label in name.split(".")))


def validate_config(data: object) -> dict:
    require(isinstance(data, dict) and set(data) == {"version", "sites"}
            and type(data["version"]) is int and data["version"] == 1,
            "Invalid configuration format")
    sites = data["sites"]
    require(isinstance(sites, dict) and len(sites) <= 25, "Invalid site registry")
    fields = {"host", "user", "port", "domain", "type", "slug", "health_url"}
    for site_id, site in sites.items():
        require(isinstance(site_id, str) and bool(ID.fullmatch(site_id)), "Invalid site ID")
        require(isinstance(site, dict) and set(site) == fields,
                f"{site_id}: invalid or unknown config fields")
        require(dns_name_ok(site["host"], HOST), f"{site_id}: invalid SSH host")
        require(isinstance(site["user"], str) and bool(USER.fullmatch(site["user"])),
                f"{site_id}: invalid Hostinger SSH user")
        require(type(site["port"]) is int and 1 <= site["port"] <= 65535,
                f"{site_id}: invalid SSH port")
        require(dns_name_ok(site["domain"], DOMAIN), f"{site_id}: invalid domain")
        require(site["type"] in ("theme", "plugin"), f"{site_id}: only theme/plugin")
        require(isinstance(site["slug"], str) and bool(SLUG.fullmatch(site["slug"])),
                f"{site_id}: invalid slug")
        url = site["health_url"]
        require(isinstance(url, str) and len(url) <= 350, f"{site_id}: invalid health URL")
        parts = urlsplit(url)
        require(parts.scheme == "https"
                and parts.hostname in (site["domain"].lower(), "www." + site["domain"].lower())
                and parts.port is None and parts.username is None and parts.password is None
                and not parts.fragment, f"{site_id}: health URL must be HTTPS on exact domain")
    return sites


def destination(site: dict) -> str:
    directory = "themes" if site["type"] == "theme" else "plugins"
    return (f"/home/{site['user']}/domains/{site['domain']}/public_html/"
            f"wp-content/{directory}/{site['slug']}")


def inspect_payload(site_id: str, site: dict, root: Path = ROOT) -> Path:
    base = root / "payload"
    path = base / site_id
    require(base.is_dir() and not base.is_symlink(), "Missing or unsafe payload directory")
    require(path.is_dir() and not path.is_symlink(), f"{site_id}: payload not found")
    require(path.resolve().is_relative_to(root.resolve()), "Payload escapes repository")
    count = 0
    total = 0
    for entry in path.rglob("*"):
        require(not entry.is_symlink(), "Payload contains symlink")
        require(entry.is_file() or entry.is_dir(), "Payload contains unsupported special file")
        require(all(not part.startswith(".") and part not in BANNED and
                    not part.startswith("id_rsa") and not part.startswith("id_ed25519")
                    for part in entry.relative_to(path).parts), "Payload contains unsafe filename")
        if entry.is_file():
            require(entry.suffix.lower() not in BANNED_SUFFIXES,
                    "Payload contains credentials or database file")
            count += 1
            total += entry.stat().st_size
            require(count <= MAX_FILES and total <= MAX_BYTES, "Payload exceeds limits")
    require(count > 0, "Payload is empty")
    if site["type"] == "theme":
        require((path / "style.css").is_file(), "Theme payload needs style.css")
    else:
        require(any(p.is_file() for p in path.glob("*.php")),
                "Plugin payload needs a root PHP file")
    return path


def ssh_options(site: dict, key: Path, known_hosts: Path) -> list[str]:
    return ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "ConnectTimeout=15", "-o", "ConnectionAttempts=1",
            "-o", "LogLevel=ERROR", "-i", str(key), "-p", str(site["port"])]


def command(args: list[str], timeout: int = 180) -> str:
    try:
        process = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                 check=False, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise Blocked("Command timed out") from exc
    except OSError as exc:
        raise Blocked(f"Required executable unavailable: {args[0]}") from exc
    if process.returncode:
        raise Blocked(f"{args[0]} failed (exit {process.returncode}); check SSH/target permissions")
    return process.stdout


def verify_remote(site: dict, ssh: list[str]) -> None:
    path = destination(site)
    p = shlex.quote(path)
    shell = ("command -v rsync >/dev/null && "
             f"test -d {p} && test -w {p} && test ! -L {p} && "
             f'test "$(readlink -f -- {p})" = {p}')
    command(ssh + [f"{site['user']}@{site['host']}", shell])


def synchronize(site: dict, source: Path, ssh: list[str], *, dry_run: bool) -> str:
    args = ["rsync", "--recursive", "--compress", "--checksum",
            "--no-perms", "--no-owner", "--no-group", "--no-times",
            "--omit-dir-times", "--itemize-changes", "--timeout=60"]
    args.append("--dry-run" if dry_run else "--delay-updates")
    args += ["-e", shlex.join(ssh), str(source) + "/",
             f"{site['user']}@{site['host']}:{destination(site)}/"]
    return command(args, timeout=600)


def healthcheck(site: dict) -> None:
    class SameSiteRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            url = urlsplit(newurl)
            if (url.scheme != "https" or url.hostname not in
                    (site["domain"].lower(), "www." + site["domain"].lower())
                    or url.port is not None):
                raise Blocked("Website redirected outside selected domain")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    try:
        opener = request.build_opener(SameSiteRedirect)
        with opener.open(request.Request(site["health_url"],
                         headers={"User-Agent": "Webactueel-SSH-Deploy/1"}), timeout=20) as page:
            require(page.status == 200, "Website did not return HTTP 200")
            body = page.read(32768).lower()
            require(body, "Website returned empty response")
            require(not any(x in body for x in
                    (b"fatal error:", b"error establishing a database connection",
                     b"there has been a critical error")), "Website returned a fatal error")
    except (OSError, ValueError) as exc:
        raise Blocked("Website HTTPS healthcheck failed") from exc


def execute(mode: str, site_id: str, confirmation: str, config: dict,
            root: Path = ROOT) -> None:
    sites = validate_config(config)
    require(site_id in sites, "Unknown site ID in HOSTINGER_SITES_JSON")
    site = sites[site_id]
    if mode == "deploy":
        require(confirmation == f"DEPLOY:{site_id}",
                f"Confirmation must be DEPLOY:{site_id}")
    require(mode in ("connect", "preview", "deploy"), "Unsupported action")
    source = inspect_payload(site_id, site, root) if mode != "connect" else None
    key = os.environ.get("HOSTINGER_SSH_PRIVATE_KEY", "")
    hosts = os.environ.get("HOSTINGER_SSH_KNOWN_HOSTS", "")
    require(key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
            and key.rstrip().endswith("-----END OPENSSH PRIVATE KEY-----"),
            "Missing or invalid HOSTINGER_SSH_PRIVATE_KEY")
    require(hosts.strip() and any(t in hosts for t in
            ("ssh-ed25519", "ecdsa-sha2-", "ssh-rsa")),
            "Missing verified HOSTINGER_SSH_KNOWN_HOSTS")
    with tempfile.TemporaryDirectory(prefix="hostinger-ssh-") as tmp:
        directory = Path(tmp)
        os.chmod(directory, 0o700)
        key_file, hosts_file = directory / "key", directory / "known_hosts"
        key_file.write_text(key.rstrip("\n") + "\n", encoding="utf-8")
        hosts_file.write_text(hosts.rstrip("\n") + "\n", encoding="utf-8")
        os.chmod(key_file, 0o600)
        os.chmod(hosts_file, 0o600)
        ssh = ssh_options(site, key_file, hosts_file)
        print(f"Checking SSH target: {site_id}")
        verify_remote(site, ssh)
        if mode == "connect":
            print("CONNECT OK: no files changed")
            return
        assert source is not None
        diff = synchronize(site, source, ssh, dry_run=True)
        print("PREVIEW:\n" + (diff.strip() or "(no file differences)"))
        if mode == "preview":
            print("PREVIEW OK: no files changed")
            return
        print("Deploying only files inside the selected theme/plugin directory")
        synchronize(site, source, ssh, dry_run=False)
        pending = synchronize(site, source, ssh, dry_run=True)
        require(not pending.strip(), "Remote files differ after upload; inspect before retrying")
        print("File checksum readback OK")
        healthcheck(site)
        print("DEPLOY OK: basic website healthcheck passed (further QA is manual)")


def main() -> int:
    p = argparse.ArgumentParser(description="Guarded Hostinger SSH/rsync")
    p.add_argument("mode", choices=["validate", "connect", "preview", "deploy"])
    p.add_argument("--site", default="")
    p.add_argument("--confirm", default="")
    p.add_argument("--config", default="")
    args = p.parse_args()
    try:
        if args.mode == "validate":
            require(args.config, "Supply --config for validating an example JSON file")
            sites = validate_config(json.loads(Path(args.config).read_text()))
            print(f"Configuration valid ({len(sites)} site(s))")
        else:
            raw = os.environ.get("HOSTINGER_SITES_JSON", "")
            require(raw.strip(), "Configure HOSTINGER_SITES_JSON secret first")
            execute(args.mode, args.site, args.confirm, json.loads(raw))
        return 0
    except (Blocked, ValueError, TypeError, OSError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
