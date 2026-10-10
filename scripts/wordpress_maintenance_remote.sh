#!/usr/bin/env bash
# Fixed-purpose, manually dispatched Hostinger-1 maintenance runner.
# Executes the existing server updater; does not install scripts or create backups.
set -uo pipefail
IFS=$'\n\t'

mode="${1:-}"
expected_script="${2:-}"
expected_inventory="${3:-}"
root="$HOME/domains"
script="$root/update_wordpress.sh"

is_digest() { [[ "$1" =~ ^[0-9a-f]{64}$ ]]; }
if [[ "$mode" != preflight && "$mode" != update ]]; then exit 10; fi
if [[ "$mode" == preflight && ( -n "$expected_script" || -n "$expected_inventory" ) ]]; then exit 10; fi
if [[ "$mode" == update ]] && { ! is_digest "$expected_script" || ! is_digest "$expected_inventory"; }; then exit 10; fi
if [[ ! -d "$root" || -L "$root" || ! -f "$script" || -L "$script" || ! -r "$script" ]]; then exit 11; fi
if ! bash -n -- "$script" >/dev/null 2>&1; then exit 12; fi
if command -v wp >/dev/null 2>&1; then
  wp_cli="$(command -v wp)"
elif [[ -x /usr/local/bin/wp ]]; then
  wp_cli=/usr/local/bin/wp
else
  exit 13
fi

# Discover both conventional and non-conventional WordPress roots without
# following symlinks; any unsupported layout blocks UPDATE (no silent omission).
site_paths=()
site_domains=()
unsupported_count=0
multisite_count=0
# Stable, non-sensitive reason categories for public GitHub Actions logs.
# No domain names or absolute filesystem paths are printed.
diag_nonstandard=0
diag_invalid_domain=0
diag_symlink=0
diag_incomplete=0
diag_core_unavailable=0
diag_home_unavailable=0
diag_home_mismatch=0
# Read-only, public-log-safe classifications of nonstandard installations.
# These fields are diagnostic only and never permit skipping a WP installation.
nested_inside_public=0
nested_outside_public=0
nested_db_installed=0
nested_db_unavailable=0
inventory_hash=""
mark_unsupported() {
  local reason="$1"
  ((unsupported_count += 1))
  case "$reason" in
    nonstandard) ((diag_nonstandard += 1)) ;;
    invalid_domain) ((diag_invalid_domain += 1)) ;;
    symlink) ((diag_symlink += 1)) ;;
    incomplete) ((diag_incomplete += 1)) ;;
    core_unavailable) ((diag_core_unavailable += 1)) ;;
    home_unavailable) ((diag_home_unavailable += 1)) ;;
    home_mismatch) ((diag_home_mismatch += 1)) ;;
    *) return 1 ;;
  esac
}
emit_diagnostics() {
  local suffix="$1"
  printf 'MAINT\tDIAG_NONSTANDARD%s\t%s\n' "$suffix" "$diag_nonstandard"
  printf 'MAINT\tDIAG_INVALID_DOMAIN%s\t%s\n' "$suffix" "$diag_invalid_domain"
  printf 'MAINT\tDIAG_SYMLINK%s\t%s\n' "$suffix" "$diag_symlink"
  printf 'MAINT\tDIAG_INCOMPLETE%s\t%s\n' "$suffix" "$diag_incomplete"
  printf 'MAINT\tDIAG_CORE_UNAVAILABLE%s\t%s\n' "$suffix" "$diag_core_unavailable"
  printf 'MAINT\tDIAG_HOME_UNAVAILABLE%s\t%s\n' "$suffix" "$diag_home_unavailable"
  printf 'MAINT\tDIAG_HOME_MISMATCH%s\t%s\n' "$suffix" "$diag_home_mismatch"
  printf 'MAINT\tNESTED_INSIDE_PUBLIC%s\t%s\n' "$suffix" "$nested_inside_public"
  printf 'MAINT\tNESTED_OUTSIDE_PUBLIC%s\t%s\n' "$suffix" "$nested_outside_public"
  printf 'MAINT\tNESTED_DB_INSTALLED%s\t%s\n' "$suffix" "$nested_db_installed"
  printf 'MAINT\tNESTED_DB_UNAVAILABLE%s\t%s\n' "$suffix" "$nested_db_unavailable"
}

discover_sites() {
  site_paths=()
  site_domains=()
  unsupported_count=0
  multisite_count=0
  diag_nonstandard=0
  diag_invalid_domain=0
  diag_symlink=0
  diag_incomplete=0
  diag_core_unavailable=0
  diag_home_unavailable=0
  diag_home_mismatch=0
  nested_inside_public=0
  nested_outside_public=0
  nested_db_installed=0
  nested_db_unavailable=0
  local candidates file site domain name actual
  candidates="$(mktemp)" || return 1
  if ! find -P "$root" -mindepth 2 \
      \( -type d \( -name wp-content -o -name node_modules -o -name vendor -o -name .git -o -name backups -o -name backup \) -prune \) -o \
      \( -type f -name wp-load.php -print0 \) > "$candidates"; then
    rm -f -- "$candidates"
    return 1
  fi
  if ! LC_ALL=C sort -z "$candidates" -o "$candidates"; then
    rm -f -- "$candidates"
    return 1
  fi
  while IFS= read -r -d '' file; do
    site="${file%/wp-load.php}"
    [[ -f "$site/wp-includes/version.php" ]] || { mark_unsupported incomplete; continue; }
    actual="$(realpath -e -- "$site")" || { rm -f -- "$candidates"; return 1; }
    [[ "$site" == "$actual" ]] || { mark_unsupported symlink; continue; }
    name="${site#"$root"/}"
    domain="${name%/public_html}"
    # Only standard layout $HOME/domains/<domain>/public_html is currently
    # supported by the original bulk updater; do not assume subdirectories.
    if [[ "$name" != "$domain/public_html" || "$domain" == */* ]]; then
      # No domains, paths, or WordPress configuration ever leave the server.
      # A nonstandard root can be a live site, so it still blocks UPDATE.
      if [[ "$name" == */public_html/* ]]; then
        ((nested_inside_public += 1))
      else
        ((nested_outside_public += 1))
      fi
      if "$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color core is-installed >/dev/null 2>&1; then
        ((nested_db_installed += 1))
      else
        ((nested_db_unavailable += 1))
      fi
      mark_unsupported nonstandard
      continue
    fi
    if [[ ! "$domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$ || "$domain" == *..* ]]; then
      mark_unsupported invalid_domain
      continue
    fi
    site_paths+=("$site")
    site_domains+=("$domain")
    if ! "$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color core is-installed >/dev/null 2>&1; then
      mark_unsupported core_unavailable
    elif "$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color core is-installed --network >/dev/null 2>&1; then
      ((multisite_count += 1))
    else
      # The domain-folder name must actually be the WordPress home page.
      # Different hosts/paths are not certified by https://<folder>/.
      local home_url
      if ! home_url="$("$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color option get home 2>/dev/null)"; then
        mark_unsupported home_unavailable
      else
        case "$home_url" in
          "http://$domain"|"http://$domain/"|"https://$domain"|"https://$domain/"|\
          "http://www.$domain"|"http://www.$domain/"|"https://www.$domain"|"https://www.$domain/") : ;;
          *) mark_unsupported home_mismatch ;;
        esac
      fi
    fi
  done < "$candidates"
  rm -f -- "$candidates"
  # Symlink-based webroots also cannot be safely assumed updated.
  local link
  shopt -s nullglob
  for link in "$root"/*/public_html; do
    if [[ -L "$link" || -L "${link%/public_html}" ]]; then mark_unsupported symlink; fi
  done
  shopt -u nullglob
  if [[ "${#site_paths[@]}" -eq 0 ]]; then return 1; fi
  inventory_hash="$(printf '%s\0' "${site_paths[@]}" | sha256sum)" || return 1
  inventory_hash="${inventory_hash%% *}"
  is_digest "$inventory_hash"
}

if ! discover_sites; then exit 14; fi
before_count=${#site_paths[@]}
script_hash="$(sha256sum -- "$script")" || exit 15
script_hash="${script_hash%% *}"
printf 'MAINT\tSCRIPT_SHA256\t%s\n' "$script_hash"
printf 'MAINT\tINVENTORY_SHA256\t%s\n' "$inventory_hash"
printf 'MAINT\tWORDPRESS_COUNT\t%s\n' "$before_count"
printf 'MAINT\tUNSUPPORTED_COUNT\t%s\n' "$unsupported_count"
printf 'MAINT\tMULTISITE_COUNT\t%s\n' "$multisite_count"
emit_diagnostics ''
if (( unsupported_count > 0 || multisite_count > 0 )); then
  printf 'MAINT\tPRECHECK\tBLOCKED\n'
  exit 17
fi
if [[ "$mode" == preflight ]]; then
  printf 'MAINT\tPRECHECK\tOK\n'
  exit 0
fi
if [[ "$script_hash" != "$expected_script" || "$inventory_hash" != "$expected_inventory" ]]; then
  printf 'MAINT\tPRECHECK\tMISMATCH\n'
  exit 18
fi
# Recheck just before execution; never trust an unreviewed different script.
current_hash="$(sha256sum -- "$script")" || exit 15
[[ "${current_hash%% *}" == "$expected_script" && ! -L "$script" ]] || exit 18
printf 'MAINT\tPRECHECK\tOK\n'

umask 077
log_dir="$HOME/.wordpress-maintenance-logs"
[[ ! -L "$log_dir" ]] || exit 16
mkdir -p -- "$log_dir" || exit 16
chmod 700 -- "$log_dir" || exit 16
log_file="$log_dir/update-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
: > "$log_file" || exit 16
chmod 600 -- "$log_file" || exit 16

# Existing update script receives the original working directory $HOME/domains.
# The raw log is private. Never relay it or site URLs to public Actions logs.
(cd "$root" && bash -- "$script" </dev/null) >>"$log_file" 2>&1
update_rc=$?
printf 'MAINT\tUPDATE_EXIT\t%s\n' "$update_rc"

# Attempt post-update checks even for a partially failed updater.
discover_sites
inventory_rc=$?
after_count=${#site_paths[@]}
printf 'MAINT\tWORDPRESS_AFTER\t%s\n' "$after_count"
printf 'MAINT\tUNSUPPORTED_AFTER\t%s\n' "$unsupported_count"
printf 'MAINT\tMULTISITE_AFTER\t%s\n' "$multisite_count"
emit_diagnostics _AFTER
post_inventory_hash="$inventory_hash"
cache_ok=0
cache_failed=0
wp_ok=0
wp_failed=0
check_failed=0
pending_updates=0

# A numeric count is reliable; on abnormal WP-CLI output mark the check failed.
wp_pending_count() {
  local site="$1" result
  shift
  if ! result="$("$wp_cli" --path="$site" --skip-themes --no-color "$@" 2>>"$log_file")"; then
    ((check_failed += 1)); return 1
  fi
  if [[ "$result" =~ ^[[:space:]]*[0-9]+[[:space:]]*$ ]]; then
    result="${result//[[:space:]]/}"
    ((pending_updates += 10#$result))
  else
    ((check_failed += 1)); return 1
  fi
  return 0
}

for i in "${!site_paths[@]}"; do
  site="${site_paths[$i]}"
  domain="${site_domains[$i]}"
  printf 'MAINT\tSITE\t%s\n' "$domain"
  site_cache_ok=1
  if ! "$wp_cli" --path="$site" --skip-themes --no-color cache flush >>"$log_file" 2>&1; then site_cache_ok=0; fi

  if "$wp_cli" --path="$site" --skip-themes --no-color plugin is-active litespeed-cache >>"$log_file" 2>&1; then
    if ! "$wp_cli" --path="$site" --skip-themes --no-color litespeed-purge all >>"$log_file" 2>&1; then site_cache_ok=0; fi
  fi
  if "$wp_cli" --path="$site" --skip-themes --no-color plugin is-active wp-rocket >>"$log_file" 2>&1; then
    if "$wp_cli" --path="$site" --skip-themes --no-color cli has-command 'rocket clean' >>"$log_file" 2>&1; then
      if ! "$wp_cli" --path="$site" --skip-themes --no-color rocket clean --confirm >>"$log_file" 2>&1; then site_cache_ok=0; fi
    elif ! "$wp_cli" --path="$site" --skip-themes --no-color eval \
      'if (!function_exists("rocket_clean_domain")) { exit(2); } rocket_clean_domain();' >>"$log_file" 2>&1; then
      site_cache_ok=0
    fi
  fi
  if ((site_cache_ok == 1)); then ((cache_ok += 1)); else ((cache_failed += 1)); fi

  if "$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color core is-installed >>"$log_file" 2>&1 \
    && "$wp_cli" --path="$site" --no-color eval 'echo "WORDPRESS_RUNTIME_OK";' >>"$log_file" 2>&1; then
    ((wp_ok += 1))
  else
    ((wp_failed += 1))
  fi
  # Check for remaining updates; do not install anything here.
  wp_pending_count "$site" core check-update --force-check --format=count || :
  wp_pending_count "$site" plugin list --update=available --format=count || :
  wp_pending_count "$site" theme list --update=available --format=count || :
  wp_pending_count "$site" language core list --status=installed --update=available --format=count || :
  wp_pending_count "$site" language plugin list --all --status=installed --update=available --format=count || :
  wp_pending_count "$site" language theme list --all --status=installed --update=available --format=count || :
  if ! "$wp_cli" --path="$site" --skip-plugins --skip-themes --no-color eval \
    'global $wp_db_version; if ((int) get_option("db_version") !== (int) $wp_db_version) { exit(9); }' >>"$log_file" 2>&1; then
    ((check_failed += 1))
  fi
done

# A successful exit code is not enough; catch definite failures recorded in
# the updater and WP-CLI output (including PHP fatal errors and WP warnings).
error_signatures=0
if grep -Eiq '(^|[[:space:]])(PHP (Fatal error|Parse error|Warning):|Fatal error:|Parse error:|Error:|ERROR:|FOUT:|WARNING:|WARN:|LET OP:|\[ERROR\]|KLAAR MET WAARSCHUWINGEN|Traceback \(most recent call last\)|Uncaught (Error|Exception)|There has been a critical error)' "$log_file"; then
  error_signatures=1
fi
printf 'MAINT\tERROR_SIGNATURES\t%s\n' "$error_signatures"
printf 'MAINT\tCACHE_OK\t%s\n' "$cache_ok"
printf 'MAINT\tCACHE_FAILED\t%s\n' "$cache_failed"
printf 'MAINT\tWP_OK\t%s\n' "$wp_ok"
printf 'MAINT\tWP_FAILED\t%s\n' "$wp_failed"
printf 'MAINT\tCHECK_FAILED\t%s\n' "$check_failed"
printf 'MAINT\tPENDING_UPDATES\t%s\n' "$pending_updates"
printf 'MAINT\tINVENTORY_AFTER_SHA256\t%s\n' "$post_inventory_hash"
if [[ "$update_rc" -ne 0 || "$error_signatures" -ne 0 || "$inventory_rc" -ne 0 ||
      "$post_inventory_hash" != "$expected_inventory" || "$after_count" -ne "$before_count" ||
      "$unsupported_count" -ne 0 || "$multisite_count" -ne 0 ||
      "$cache_failed" -ne 0 || "$wp_failed" -ne 0 || "$check_failed" -ne 0 || "$pending_updates" -ne 0 ]]; then
  exit 20
fi
exit 0
