#!/usr/bin/env python3
"""Read-only Hostinger migration audit. No script contents, domains or keys in public logs."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from hostinger import Blocked, require, ssh_options, validate_config, account_fingerprint, verify_hosting_binding

POLICY_FILE = Path(__file__).resolve().parents[1] / 'config/wordpress-migration-policy.json'
FIELDS = ('DOMAINS_SCRIPT', 'HOME_SCRIPT', 'HOME_EXCLUSION',
          'DOMAINS_SCRIPT_SYNTAX', 'HOME_SCRIPT_SYNTAX', 'HOME_EXCLUSION_SYNTAX',
          'WP_CLI', 'DOMAIN_DIRS', 'DOMAIN_NAMES_SHA256', 'SCRIPT_CANDIDATES',
          'MATCHING_EXCLUSION_FILES', 'CANDIDATE_TRUNCATED', 'CANDIDATE_SCAN_PERFORMED', 'CANDIDATE_ERRORS', 'SOURCE_ACCOUNT_SPECIFIC')
DIGEST_FIELDS = {'DOMAINS_SCRIPT', 'HOME_SCRIPT', 'HOME_EXCLUSION', 'DOMAIN_NAMES_SHA256'}
ABSENT = '0' * 64
REMOTE = r'''#!/usr/bin/env bash
set -euo pipefail
root="$HOME/domains"
expected="$1"
[[ -d "$root" && ! -L "$root" ]] || exit 41
command -v sha256sum >/dev/null
hash_script() {
  local file="$1" label="$2" digest syntax
  if [[ -e "$file" || -L "$file" ]]; then
    [[ -f "$file" && ! -L "$file" && -r "$file" ]] || exit 42
    if bash -n -- "$file" >/dev/null 2>&1; then syntax=1; else syntax=0; fi
    digest="$(sha256sum -- "$file" | cut -d ' ' -f 1)"
    printf 'SCRIPT_AUDIT\t%s\t%s\n' "$label" "$digest"
    printf 'SCRIPT_AUDIT\t%s_SYNTAX\t%s\n' "$label" "$syntax"
  else
    printf 'SCRIPT_AUDIT\t%s\t0000000000000000000000000000000000000000000000000000000000000000\n' "$label"
    printf 'SCRIPT_AUDIT\t%s_SYNTAX\t0\n' "$label"
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
name_sha="$(find -P "$root" -mindepth 1 -maxdepth 1 -type d -printf '%f\0' | LC_ALL=C sort -z | sha256sum | cut -d ' ' -f1)"
printf 'SCRIPT_AUDIT\tDOMAIN_NAMES_SHA256\t%s\n' "$name_sha"
# Only Hostinger 2 needs legacy-profile discovery. Other environments
# report ordinary script slots only, avoiding needless reads of private files.
candidates=0
matches=0
truncated=0
performed=0
errors=0
if [[ "$expected" != "0000000000000000000000000000000000000000000000000000000000000000" ]]; then
  performed=1
  for base in "$HOME" "$HOME/domains" "$HOME/scripts" "$HOME/bin" "$HOME/tools"; do
    [[ -d "$base" && ! -L "$base" ]] || continue
    while IFS= read -r -d '' candidate; do
      ((candidates += 1))
      if ((candidates > 150)); then
        truncated=1
        break
      fi
      if [[ ! -L "$candidate" && -r "$candidate" ]]; then
        if digest="$(sha256sum -- "$candidate" | cut -d ' ' -f1)"; then
          if [[ "$digest" == "$expected" ]]; then ((matches += 1)); fi
        else
          ((errors += 1))
        fi
      fi
    done < <(find -P "$base" -mindepth 1 -maxdepth 1 -type f \
      \( -iname '*wordpress*.sh' -o -iname '*update*.sh' \) -print0)
    if ((truncated == 1)); then break; fi
  done
fi
printf 'SCRIPT_AUDIT\tSCRIPT_CANDIDATES\t%s\n' "$candidates"
printf 'SCRIPT_AUDIT\tMATCHING_EXCLUSION_FILES\t%s\n' "$matches"
printf 'SCRIPT_AUDIT\tCANDIDATE_TRUNCATED\t%s\n' "$truncated"
printf 'SCRIPT_AUDIT\tCANDIDATE_SCAN_PERFORMED\t%s\n' "$performed"
printf 'SCRIPT_AUDIT\tCANDIDATE_ERRORS\t%s\n' "$errors"
specific=0
if [[ -f "$root/update_wordpress.sh" && ! -L "$root/update_wordpress.sh" ]]; then
  if grep -Eq '/home/u[0-9]{4,16}' "$root/update_wordpress.sh"; then specific=1; fi
fi
printf 'SCRIPT_AUDIT\tSOURCE_ACCOUNT_SPECIFIC\t%s\n' "$specific"
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
        if field in DIGEST_FIELDS:
            require(re.fullmatch(r'[0-9a-f]{64}', value) is not None, 'Invalid digest')
        else:
            require(value.isascii() and value.isdecimal() and len(value) <= 6, 'Invalid count')
        result[field] = value
    require(set(result) == set(FIELDS),
            'Incomplete SSH audit response: ' + ','.join(sorted(set(FIELDS) - set(result))))
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
        expected = load_policy()['hostinger-2']['legacy_sha256'] if hosting == 'hostinger-2' else ABSENT
        args = ssh_options(account, key, hosts) + [f"{account['user']}@{account['host']}", 'bash -s -- ' + expected]
        try:
            run = subprocess.run(args, input=REMOTE, text=True, capture_output=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Blocked('SSH inspection unavailable') from exc
    require(run.stdout.strip(), f'SSH inspection failed (exit {run.returncode})')
    if run.returncode != 0:
        raise Blocked(f"Remote read-only scanner stopped (exit {run.returncode})")
    return parse_ssh_output(run.stdout), run.returncode


def evaluate(hosting, inventory, returncode, policy):
    print('Hosting environment:', hosting)
    for key in ('DOMAINS_SCRIPT', 'HOME_SCRIPT', 'HOME_EXCLUSION'):
        value = inventory[key]
        syntax = inventory[key + '_SYNTAX']
        print(f'{key}:', 'afwezig' if value == ABSENT else 'SHA-256 ' + value,
              '(Bash syntax OK)' if syntax == '1' else '(ontbreekt of Bash syntax fout)')
    print('Domeinmappen:', inventory['DOMAIN_DIRS'])
    print('Domein-inventaris fingerprint:', inventory['DOMAIN_NAMES_SHA256'])
    print('Update-scriptkandidaten buiten webroots:', inventory['SCRIPT_CANDIDATES'])
    print('Historische exclusieprofielmatches:', inventory['MATCHING_EXCLUSION_FILES'])
    print('Scriptzoeklimiet bereikt:', 'JA' if inventory['CANDIDATE_TRUNCATED'] == '1' else 'NEE')
    print('Legacy-exclusiezoektocht uitgevoerd:', 'JA' if inventory['CANDIDATE_SCAN_PERFORMED'] == '1' else 'NEE')
    print('Fouten bij lezen scriptkandidaten:', inventory['CANDIDATE_ERRORS'])
    if hosting == 'hostinger-1':
        print('Accountspecifieke absolute paden in bronscript:',
              'JA' if inventory['SOURCE_ACCOUNT_SPECIFIC'] == '1' else 'NEE')
    print('WP-CLI:', 'gevonden' if inventory['WP_CLI'] == '1' else 'ontbreekt')
    if hosting == 'hostinger-2':
        same = (inventory['HOME_EXCLUSION'] == policy['hostinger-2']['legacy_sha256']
                or int(inventory['MATCHING_EXCLUSION_FILES']) > 0)
        print('Historisch exclusieprofiel ergens buiten webroot gevonden:',
              'JA' if same else 'NEE')
        print('Dit bevestigt niet dat de huidige actieve updater dezelfde uitsluitingen heeft.')
        print('Hostinger 2: zes historische uitsluitingen moeten behouden blijven')
        if not same:
            return False
    if any(inventory[k] != ABSENT and inventory[k + '_SYNTAX'] != '1'
           for k in ('DOMAINS_SCRIPT', 'HOME_SCRIPT', 'HOME_EXCLUSION')):
        print('STATUS: BLOCKED — een bestaand script heeft ongeldige Bash-syntax')
        return False
    if (inventory['CANDIDATE_TRUNCATED'] == '1'
            or inventory['CANDIDATE_ERRORS'] != '0'):
        print('STATUS: BLOCKED — scriptzoektocht niet volledig of niet betrouwbaar')
        return False
    if (hosting == 'hostinger-2') != (inventory['CANDIDATE_SCAN_PERFORMED'] == '1'):
        print('STATUS: BLOCKED — onverwachte zoekscope')
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
        config = json.loads(raw)
        fingerprint = verify_hosting_binding(config, hosting)
        print("Account-identiteit SHA-256:", fingerprint)
        inventory, code = inspect(hosting, config,
                                  os.environ.get('HOSTINGER_SSH_PRIVATE_KEY', ''),
                                  os.environ.get('HOSTINGER_SSH_KNOWN_HOSTS', ''))
        return 0 if evaluate(hosting, inventory, code, policy) else 1
    except (Blocked, ValueError, TypeError, OSError) as exc:
        print('BLOCKED:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
