# Repository policy - Yolol100/onderhoud

One authorized SSH connection per Hostinger hosting package. The WordPress
release owner is wordpressqualityarchitect; controller is webactueel-workflow.
This repository is transport, not a second controller.

- Environment naming starts at `hostinger-1` and increases consecutively
  to `hostinger-10`; there is no unnumbered `hostinger` default.
- Each GitHub Environment has its **own** three secrets:
  `HOSTINGER_SSH_PRIVATE_KEY`, `HOSTINGER_SSH_KNOWN_HOSTS`,
  `HOSTINGER_SITES_JSON`.
- Do not put actual SSH usernames/hosts, credential contents, client details,
  known_hosts, customer data or sensitive domains in public repo files/logs.
- Use one distinct SSH private key for each hosting package. Never reuse or
  silently replace another package's key or configuration.
- Keep `connect` and `list` read-only; never expose domain names in logs.
- `preview` and `deploy` operate only on explicit theme/plugin targets.
  Require a bounded payload, validated non-symlink paths, strict hostkeys,
  typed deploy confirmation and checksum readback.
- No arbitrary shell inputs, SQL, cronjobs, scheduled actions, backup jobs or
  `rsync --delete`.
- Read-only `hostinger1-ssh-preflight.yml` may trigger automatically on
  `main` pushes to audited script/workflow paths. It must use the existing
  fixed-purpose preflight only, the Hostinger-1 Environment, strict hostkeys,
  no domain names in logs, and cannot execute any update command.
- Multi-account `hostinger-wordpress-migration-audit.yml` is read-only. Each job uses only its matching existing GitHub Environment secret. Verify Hostinger-2 exclusions against the pinned historical script SHA; do not upload private script contents or overwrite remote files. This is not update/deployment authorization.
- **Single scoped exception**: manual `wordpress-onderhoud-hostinger-1.yml`
  may execute only the existing `$HOME/domains/update_wordpress.sh`, after
  preflight and typed `UPDATE:hostinger-1:ALL` confirmation. Follow with
  post-update WordPress, cache and public HTTPS checks; fail closed. The
  original SSH/deploy workflow stays unchanged. Do not add recurring updates
  or allow other environments until separately authorized.
- The maintenance wrapper creates no backups. It cannot guarantee Hostinger
  backups or the behavior of the independently maintained server script.
- GitHub CI success is not a live SSH or WordPress website QA result.
- Tests: `python3 -m unittest discover -s tests -v` and
  `bash -n scripts/wordpress_maintenance_remote.sh`.
- Validate: `python3 scripts/hostinger.py validate --config config/sites.example.json`.