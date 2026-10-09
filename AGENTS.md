# Repository policy - Yolol100/onderhoud

GitHub Actions uses one authorized Hostinger SSH account as a transport, never
as a new Webactueel controller. Owner: wordpressqualityarchitect.
Controller: webactueel-workflow.

- Account-wide \`connect\` and \`list\` are read-only; no site ID required.
- Never list client domains, secrets, environment values, raw credentials
  or private files into public GitHub Actions logs.
- Account \`host\`, \`user\`, \`port\` live in \`HOSTINGER_SITES_JSON\`
  version 2, kept exclusively in the GitHub \`hostinger\` environment secret.
- Only explicit named theme/plugin targets may \`preview\` and \`deploy\`.
- Never add arbitrary remote-shell input, WordPress core maintenance,
  update batches, SQL, scheduled actions, automatic backups, rollback jobs
  or \`rsync --delete\`.
- Use strict SSH hostkey pinning, scoped paths, symlink checks,
  typed deploy confirmation and checksum readback.
- Do not assume a green GitHub run equals end-to-end website QA.
- Hostinger's existing backup service remains provider-owned.
- CI: \`python3 -m unittest discover -s tests -v\`.
- Validate sample: \`python3 scripts/hostinger.py validate --config config/sites.example.json\`.
