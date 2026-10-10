#!/usr/bin/env python3
"""Read-only Hostinger migration audit. No script contents, domains or keys in public logs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from hostinger import Blocked, require, ssh_options, validate_config

POLICY_FILE = Path(__file__).resolve().parents[1] / 'config/wordpress-migration-policy.json'
FIELDS = ('DOMAINS_SCRIPT', 'HOME_SCRIPT', 'HOME_EXCLUSION', 'WP_CLI', 'DOMAIN_DIRS')
ABSENT = '0' * 64
REMOTE = r'''#!/usr/bin/env bash
set -euo pipefail
root="$HOME/domains"
[[ -d "$root" && ! -L "$root" ]] || exit 41
command -v sha256sum >/dev/null
hash_script() {
  local file="$1" label="$2" digest
  if [[ -e "$file" || -L "$file" ]]; then
    [[ -f "$file" && ! -L "$file" && -r "$file" ]] || exit 42
    bash -n -- "$file" >/dev/null 2>&1 || exit 43
    digest="$(sha256sum -- "$file" | cut -d ' ' -f 1)"
    printf 'SCRIPT_AUDIT\t%s\t%s\n' "$label" "$digest"
  else
    printf 'SCRIPT_AUDIT\t%s\t0000000000000000000000000000000000000000000000000000000000000000\n' "$label"
  fi
}
hash_script "$root/update_wordpress.sh" DOMAINS_SCRIPT
hash_script "$HOME/update_wordpress.sh" HOME_SCRIPT
hash_script "$HOME/update_wordpress_exclusion.sh" HOME_EXCLUSION
if command -v wp >/dev/null 2>&1 || [[ -x /usr/local/bin/wp ]]; then
  printf 'SCRIPT_AUDIT\tWP_CLI\t1\n'
else
  printf 'SCRIPT_AUDIT\tWP_CLI\t0\n'
fi
count="$(find -P "$root" -mindepth 1 -maxdepth 1 -type d -print | wc -l | tr -d '[:space:]')"
[[ "$count" =~ ^[0-9]+$ ]] || exit 45
printf 'SCRIPT_AUDIT\tDOMAIN_DIRS\t%s\n' "$count"
'''


def load_policy(path=POLICY_FILE):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    require(isinstance(data, dict) and set(data) == {'version', 'hostinger-2'}, 'Invalid policy structure')
    require(data['version'] == 1 and type(data['version']) is int, 'Invalid policy version')
    rules = data['hostinger-2']
    require(set(rules) == {'legacy_sha256', 'excluded_plugins'}, 'Invalid Hostinger 2 rules')
    require(re.fullmatch(r'[0-9a-f]{64}', rules['legacy_sha256']) is not None, 'Invalid legacy digest')
    slugs = rules['excluded_plugins']
    require(isinstance(slugs, list) and len(slugs) == 6 and len(set(slugs)) == 6
            and all(isinstance(s, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', s) for s in slugs),
            'Invalid Hostinger 2 plugin exclusions')
    return data


def parse_ssh_output(text):
    require(len(text) <= 2048, 'Oversized SSH audit response')
    result = {}
    for line in text.splitlines():
        parts = line.split('\t')
        require(len(parts) == 3 and parts[0] == 'SCRIPT_AUDIT', 'Unexpected SSH response')
        _, field, value = parts
        require(field in FIELDS and field not in result, 'Invalid/duplicate SSH field')
        if field in FIELDS[:3]:
            require(re.fullmatch(r'[0-9a-f]{64}', value) is not None, 'Invalid digest')
        else:
            require(value.isascii() and value.isdecimal() and len(value) <= 6, 'Invalid count')
        result[field] = value
    require(set(result) == set(FIELDS), 'Incomplete SSH audit response')
    return result


def inspect(hosting, config, ssh_key, known_hosts):
    require(re.fullmatch(r'hostinger-(?:[1-9]|10)', hosting) is not None, 'Invalid hosting ID')
    account = validate_config(config)['account']
    require(ssh_key.startswith('-----BEGIN OPENSSH PRIVATE KEY-----')
            and ssh_key.rstrip().endswith('-----END OPENSSH PRIVATE KEY-----'), 'SSH key missing')
    require(known_hosts.strip() and any(x in known_hosts for x in ('ssh-ed25519', 'ecdsa-sha2-', 'ssh-rsa')),
            'Verified known_hosts missing')
    with tempfile.TemporaryDirectory(prefix='wp-script-audit-') as dirname:
        folder = Path(dirname)
        os.chmod(folder, 0o700)
        key, hosts = folder / 'id', folder / 'hosts'
        key.write_text(ssh_key.rstrip('\n') + '\n', encoding='utf-8')
        hosts.write_text(known_hosts.rstrip('\n') + '\n', encoding='utf-8')
        os.chmod(key, 0o600)
        os.chmod(hosts, 0o600)
        args = ssh_options(account, key, hosts) + [f"{account['user']}@{account['host']}", 'bash -s --']
        try:
            run = subprocess.run(args, input=REMOTE, text=True, capture_output=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Blocked('SSH inspection unavailable') from exc
    require(run.stdout.strip(), f'SSH inspection failed (exit {run.returncode})')
    return parse_ssh_output(run.stdout), run.returncode


def evaluate(hosting, inventory, returncode, policy):
    print('Hosting environment:', hosting)
    for key in FIELDS[:3]:
        print(f'{key}:', 'afwezig' if inventory[key] == ABSENT else 'SHA-256 ' + inventory[key])
    print('Domeinmappen:', inventory['DOMAIN_DIRS'])
    print('WP-CLI:', 'gevonden' if inventory['WP_CLI'] == '1' else 'ontbreekt')
    if hosting == 'hostinger-2':
        same = inventory['HOME_EXCLUSION'] == policy['hostinger-2']['legacy_sha256']
        print('Oud exclusieprofiel exact overeenkomstig:', 'JA' if same else 'NEE')
        print('Hostinger 2: zes historische uitsluitingen moeten behouden blijven')
        if not same:
            return False
    if returncode != 0:
        return False
    if hosting == 'hostinger-1' and inventory['DOMAINS_SCRIPT'] == ABSENT:
        return False
    print('AUDIT_OK: alleen gelezen, niets bijgewerkt of gekopieerd')
    return True


def main():
    try:
        hosting = os.environ.get('HOSTING_ENV', '')
        require(re.fullmatch(r'hostinger-(?:[1-9]|10)', hosting) is not None, 'Unknown environment')
        raw = os.environ.get('HOSTINGER_SITES_JSON', '')
        require(bool(raw.strip()), 'Missing HOSTINGER_SITES_JSON')
        policy = load_policy()
        inventory, code = inspect(hosting, json.loads(raw),
                                  os.environ.get('HOSTINGER_SSH_PRIVATE_KEY', ''),
                                  os.environ.get('HOSTINGER_SSH_KNOWN_HOSTS', ''))
        return 0 if evaluate(hosting, inventory, code, policy) else 1
    except (Blocked, ValueError, TypeError, OSError) as exc:
        print('BLOCKED:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
