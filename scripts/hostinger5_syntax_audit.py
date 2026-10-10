#!/usr/bin/env python3
"""Read-only, privacy-preserving Bash syntax diagnosis of Hostinger 5 updater.

The remote file is never downloaded, sourced, run, overwritten, or echoed.
Only the digest, numeric line number, and allowlisted error category appear.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from hostinger import Blocked, require, ssh_options, validate_config
from hostinger_script_migration import account_fingerprint

EXPECTED_ACCOUNT_ID = "bc8c65dd7039c81c83d26c3b4232ba46b11cb73fb9b3110957bee66db287f0ba"
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ALLOWED_CATEGORIES = {
    "NONE", "UNCLOSED_QUOTE", "UNEXPECTED_EOF", "UNEXPECTED_TOKEN",
    "HEREDOC", "OTHER",
}
FIELDS = {"SHA256", "STATUS", "CATEGORY", "LINE", "NORMALIZED_OK"}

REMOTE = r'''#!/usr/bin/env bash
set -euo pipefail
script="$HOME/domains/update_wordpress.sh"
[[ -f "$script" && -r "$script" && ! -L "$script" ]] || exit 41
before="$(sha256sum -- "$script")"
before="${before%% *}"
error=""
if error="$(bash -n -- "$script" 2>&1)"; then
  state="OK"
  category="NONE"
  number=0
else
  state="INVALID"
  category="OTHER"
  if [[ "$error" == *"unexpected EOF while looking for matching"* ]]; then
    category="UNCLOSED_QUOTE"
  elif [[ "$error" == *"here-document"* ]]; then
    category="HEREDOC"
  elif [[ "$error" == *"unexpected end of file"* ]]; then
    category="UNEXPECTED_EOF"
  elif [[ "$error" == *"syntax error near unexpected token"* ]]; then
    category="UNEXPECTED_TOKEN"
  fi
  # Never print stderr or the offending source line: both can contain secrets.
  number="$(printf '%s\n' "$error" | sed -nE 's/.*line ([0-9]+).*/\1/p' | tail -n 1)"
  [[ "$number" =~ ^[0-9]+$ ]] || number=0
fi
normal_ok=0
if LC_ALL=C sed 's/\r$//' "$script" | bash -n 2>/dev/null; then
  normal_ok=1
fi
after="$(sha256sum -- "$script")"
after="${after%% *}"
[[ "$before" == "$after" ]] || exit 42
printf 'HOST5_SYNTAX\tSHA256\t%s\n' "$before"
printf 'HOST5_SYNTAX\tSTATUS\t%s\n' "$state"
printf 'HOST5_SYNTAX\tCATEGORY\t%s\n' "$category"
printf 'HOST5_SYNTAX\tLINE\t%s\n' "$number"
printf 'HOST5_SYNTAX\tNORMALIZED_OK\t%s\n' "$normal_ok"
'''


def parse_remote_output(output: str) -> dict[str, str]:
    require(len(output) <= 2048, "Untrusted or oversized remote diagnostic")
    result: dict[str, str] = {}
    for line in output.splitlines():
        pieces = line.split("\t")
        require(len(pieces) == 3 and pieces[0] == "HOST5_SYNTAX",
                "Unexpected remote diagnostic output")
        _, key, value = pieces
        require(key in FIELDS and key not in result, "Unrecognized or duplicate field")
        result[key] = value
    require(set(result) == FIELDS, "Missing remote diagnostic fields")
    require(bool(DIGEST.fullmatch(result["SHA256"])), "Invalid script digest")
    require(result["STATUS"] in ("OK", "INVALID"), "Invalid syntax status")
    require(result["CATEGORY"] in ALLOWED_CATEGORIES, "Invalid error category")
    require(result["LINE"].isascii() and result["LINE"].isdecimal()
            and len(result["LINE"]) <= 7, "Invalid numeric line")
    require(result["NORMALIZED_OK"] in ("0", "1"), "Invalid normalized result")
    if result["STATUS"] == "OK":
        require(result["CATEGORY"] == "NONE" and result["LINE"] == "0"
                and result["NORMALIZED_OK"] == "1", "Inconsistent successful syntax check")
    else:
        require(result["CATEGORY"] != "NONE", "Inconsistent failed syntax check")
    return result


def run_diagnostic(config: dict, private_key: str, known_hosts: str) -> dict[str, str]:
    config = validate_config(config)
    require(account_fingerprint(config) == EXPECTED_ACCOUNT_ID,
            "Hostinger 5 account mismatch")
    require(private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
            and private_key.rstrip().endswith("-----END OPENSSH PRIVATE KEY-----"),
            "Hostinger 5 private key secret missing")
    require(known_hosts.strip() and any(k in known_hosts
            for k in ("ssh-ed25519", "ecdsa-sha2-", "ssh-rsa")),
            "Hostinger 5 verified hostkey missing")
    account = config["account"]
    with tempfile.TemporaryDirectory(prefix="hostinger5-readonly-") as tmp:
        folder = Path(tmp)
        os.chmod(folder, 0o700)
        key_file, hosts_file = folder / "id", folder / "hosts"
        key_file.write_text(private_key.rstrip("\n") + "\n", encoding="utf-8")
        hosts_file.write_text(known_hosts.rstrip("\n") + "\n", encoding="utf-8")
        os.chmod(key_file, 0o600)
        os.chmod(hosts_file, 0o600)
        args = ssh_options(account, key_file, hosts_file)
        args += [f"{account['user']}@{account['host']}", "bash -s --"]
        try:
            response = subprocess.run(args, input=REMOTE, text=True,
                                      capture_output=True, timeout=80, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Blocked("Cannot perform read-only Hostinger 5 syntax check") from exc
    require(response.returncode == 0, "Hostinger 5 syntax probe failed safely")
    return parse_remote_output(response.stdout)


def main() -> int:
    try:
        raw = os.environ.get("HOSTINGER_SITES_JSON", "")
        require(raw.strip(), "Hostinger 5 config secret missing")
        status = run_diagnostic(json.loads(raw),
                                os.environ.get("HOSTINGER_SSH_PRIVATE_KEY", ""),
                                os.environ.get("HOSTINGER_SSH_KNOWN_HOSTS", ""))
        print("Hostinger 5 script SHA256:", status["SHA256"])
        print("Bash syntax:", status["STATUS"])
        print("Error category:", status["CATEGORY"])
        print("Reported line number:", status["LINE"])
        print("CRLF normalization alone fixes syntax:",
              "YES" if status["STATUS"] == "INVALID"
              and status["NORMALIZED_OK"] == "1" else "NO")
        print("READ_ONLY: script was not executed, copied, edited or removed")
        return 0
    except (Blocked, ValueError, TypeError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
