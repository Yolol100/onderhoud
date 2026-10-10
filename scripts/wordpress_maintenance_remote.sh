#!/usr/bin/env bash
# Fixed-purpose runner. Sent via pinned SSH by wordpress_maintenance.py.
# This file never creates backups, changes cron, or accepts shell commands.
set -uo pipefail
IFS=$'\n\t'

mode="${1:-}"
if [[ "$mode" != "preflight" && "$mode" != "update" ]]; then
  exit 10
fi

root="$HOME/domains"
script="$root/update_wordpress.sh"
if [[ ! -d "$root" || -L "$root" || ! -f "$script" || -L "$script" || ! -r "$script" ]]; then
  exit 11
fi
if ! bash -n -- "$script" >/dev/null 2>&1; then
  exit 12
fi
if command -v wp >/dev/null 2>&1; then
  wp_cli="$(command -v wp)"
elif [[ -x /usr/local/bin/wp ]]; then
  wp_cli=/usr/local/bin/wp
else
  exit 13
fi

# Discover only non-symlink WordPress roots directly under this one account.
site_paths=()
site_domains=()
discover_sites() {
  site_paths=()
  site_domains=()
  local folder name
  shopt -s nullglob
  for folder in "$root"/*/public_html; do
    [[ -d "$folder" && ! -L "$folder" && ! -L "${folder%/public_html}" ]] || continue
    [[ -f "$folder/wp-load.php" && -f "$folder/wp-includes/version.php" ]] || continue
    name="${folder%/public_html}"
    name="${name##*/}"
    # The names are not placed in public Actions logs.
    [[ "$name" == *.* && "$name" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ && "$name" != *..* ]] || continue
    site_paths+=("$folder")
    site_domains+=("$name")
  done
  shopt -u nullglob
}
discover_sites
before_count="${#site_paths[@]}"
if [[ "$before_count" -eq 0 ]]; then
  exit 14
fi
hash_line="$(sha256sum -- "$script")" || exit 15
printf 'MAINT\tSCRIPT_SHA256\t%s\n' "${hash_line%% *}"
printf 'MAINT\tWORDPRESS_COUNT\t%s\n' "$before_count"

if [[ "$mode" == "preflight" ]]; then
  printf 'MAINT\tPRECHECK\tOK\n'
  exit 0
fi

# No backups are created by this wrapper. Its existing updater is an
# independently managed server file; check its code separately before use.
umask 077
log_dir="$HOME/.wordpress-maintenance-logs"
mkdir -p -- "$log_dir" || exit 16
chmod 700 -- "$log_dir" || exit 16
log_file="$log_dir/update-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
: > "$log_file" || exit 16
chmod 600 -- "$log_file" || exit 16

# The updater's raw output stays on the server, not in public Actions logs.
# Do not let the child consume the SSH-fed Bash script on stdin.
bash -- "$script" </dev/null >>"$log_file" 2>&1
update_rc=$?
printf 'MAINT\tUPDATE_EXIT\t%s\n' "$update_rc"

# Always run post-update cache and WordPress checks, even after a partial update.
discover_sites
after_count="${#site_paths[@]}"
printf 'MAINT\tWORDPRESS_AFTER\t%s\n' "$after_count"
cache_ok=0
cache_failed=0
wp_ok=0
wp_failed=0
for i in "${!site_paths[@]}"; do
  site="${site_paths[$i]}"
  domain="${site_domains[$i]}"
  printf 'MAINT\tSITE\t%s\n' "$domain"

  # Object-cache flush, then the enabled plugin's page-cache flush.
  if "$wp_cli" --path="$site" --skip-themes --no-color cache flush >>"$log_file" 2>&1; then
    ((cache_ok += 1))
  else
    ((cache_failed += 1))
  fi

  if "$wp_cli" --path="$site" --skip-themes --no-color plugin is-active litespeed-cache >>"$log_file" 2>&1; then
    if ! "$wp_cli" --path="$site" --skip-themes --no-color litespeed-purge all >>"$log_file" 2>&1; then
      ((cache_failed += 1))
    fi
  fi

  if "$wp_cli" --path="$site" --skip-themes --no-color plugin is-active wp-rocket >>"$log_file" 2>&1; then
    if "$wp_cli" --path="$site" --skip-themes --no-color cli has-command 'rocket clean' >>"$log_file" 2>&1; then
      if ! "$wp_cli" --path="$site" --skip-themes --no-color rocket clean --confirm >>"$log_file" 2>&1; then
        ((cache_failed += 1))
      fi
    elif ! "$wp_cli" --path="$site" --skip-themes --no-color eval \
      'if (!function_exists("rocket_clean_domain")) { exit(2); } rocket_clean_domain();' >>"$log_file" 2>&1; then
      ((cache_failed += 1))
    fi
  fi

  if "$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color core is-installed >>"$log_file" 2>&1 \
    && "$wp_cli" --path="$site" --no-color eval 'echo "WORDPRESS_RUNTIME_OK";' >>"$log_file" 2>&1; then
    ((wp_ok += 1))
  else
    ((wp_failed += 1))
  fi
done
printf 'MAINT\tCACHE_OK\t%s\n' "$cache_ok"
printf 'MAINT\tCACHE_FAILED\t%s\n' "$cache_failed"
printf 'MAINT\tWP_OK\t%s\n' "$wp_ok"
printf 'MAINT\tWP_FAILED\t%s\n' "$wp_failed"
# Exit nonzero on any failed phase or unexpected WordPress site count change.
if [[ "$update_rc" -ne 0 || "$cache_failed" -ne 0 || "$wp_failed" -ne 0 || "$after_count" -ne "$before_count" ]]; then
  exit 20
fi
exit 0
