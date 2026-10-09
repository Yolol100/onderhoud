# Hostinger SSH-account - GitHub Actions

Deze repository gebruikt **één SSH-verbinding met het Hostinger-hostingaccount**
waar jouw websites onder vallen. Je hoeft dus geen apart account of SSH-sleutel
per website aan te maken.

**Handmatig en veilig:**
- connect: controleert de SSH-verbinding voor het hele hostingaccount.
- list: telt bereikbare domeinmappen zonder klantdomeinen in openbare logs te tonen.
- preview: toont alleen verschillen in een vooraf geregistreerde plugin/thema-map.
- deploy: publiceert alleen die geselecteerde bestanden na expliciete bevestiging.

Geen automatische WordPress-updates, onderhoud, cron, SQL, back-ups, MCP of
willekeurige servercommando's. Bestaande Hostinger-back-ups worden niet aangepast.

## Begin hier

[Stappenplan voor de hele hosting](docs/INSTALLATIE.md)

De GitHub Environment \`hostinger\` bevat precies drie Secrets:
\`HOSTINGER_SSH_PRIVATE_KEY\`, \`HOSTINGER_SSH_KNOWN_HOSTS\`,
\`HOSTINGER_SITES_JSON\`. Die laatste heeft versie 2: één \`account\`
en een optionele \`sites\`-lijst. Voor een eerste verbinding mag de lijst leeg zijn.

## Technische bestanden

- \`.github/workflows/hostinger.yml\` - handmatig, alleen main, serialized
- \`.github/workflows/ci.yml\` - automatisch alleen code- en testsuite
- \`scripts/hostinger.py\` - accountcheck, veilige inventaris, beperkte deploy
- \`tests/test_hostinger.py\` - security-, input- en regressietests
- \`config/sites.example.json\` - fictief voorbeeld
- \`AGENTS.md\` - vaste grenzen

Het SSH-account heeft **alleen de rechten die Hostinger aan die gebruiker geeft**.
Dit geeft geen VPS-root, geen automatische database- of hPanel-toegang.
Er is nog geen echte GitHub → Hostinger SSH-verbinding gevalideerd.

**Let op:** repo-publicatie kan gevoelige code of loggegevens openbaar maken.
Zet geen private websitebestanden, klantenlijsten of wachtwoorden in deze repo.

## Meerdere Hostinger-hostingpakketten

De workflow heeft nu een keuzelijst **Hosting**: `hostinger` (bestaand), `hostinger-2` tot en met `hostinger-10`. Elk pakket krijgt zijn eigen GitHub Environment met de **zelfde drie secretnamen maar andere SSH-gegevens**. De bestaande koppeling `hostinger` blijft behouden. Een tweede IP of SSH-gebruiker betekent normaal een nieuwe hostingomgeving; meerdere websites onder één hostingpakket hebben die niet nodig. Zie [de stappen](docs/INSTALLATIE.md#7-meerdere-hostingpakketten-met-eigen-ip-of-ssh-gebruiker).
