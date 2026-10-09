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
- No arbitrary shell inputs, SQL, automatic WordPress/WooCommerce updates,
  cronjobs, scheduled actions, backup jobs or `rsync --delete`.
- GitHub CI success is not a live SSH or WordPress website QA result.
- Tests: `python3 -m unittest discover -s tests -v`.
- Validate: `python3 scripts/hostinger.py validate --config config/sites.example.json`.
