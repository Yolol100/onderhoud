# Repository contract - Yolol100/onderhoud

Purpose: GitHub Actions is the SSH transport for selected Hostinger-managed
WordPress theme and plugin code. Controller stays webactueel-workflow.
WordPress code/security owner: wordpressqualityarchitect.

Boundaries:
- Keep actions manual. No schedules, cron, WordPress auto-updates, WP-CLI
  maintenance batches, backup scripts, database operations or arbitrary shell.
- Never place secret values, private keys, customer data or SSH known_hosts
  in repository files or Actions output.
- Verify exact site identity, immutable scoped target path, SSH fingerprint,
  no symlinks, safe payload, dry-run, typed confirmation and checksum readback.
- Never add rsync --delete or shell commands taken from workflow input.
- Because the repository is public, do not add proprietary site code. Make
  private first, and check plan support for environment secrets.
- GitHub CI success is not live website QA or rollback proof. Stage changes
  before using production and separately test affected WooCommerce checkout.
- Hostinger handles provider backups, but this tool must not assume the
  last restore point is recent or tested.
- Run tests: python3 -m unittest discover -s tests -v
- Validate example: python3 scripts/hostinger.py validate --config config/sites.example.json
