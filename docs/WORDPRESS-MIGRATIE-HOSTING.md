# WordPress-batchscript migreren tussen Hostinger-omgevingen

## Uitvoeringsprompt (masterplan)

> Behandel het **actuele live** `$HOME/domains/update_wordpress.sh` op
> Hostinger 1 als kandidaat-bron. Breng een passende, vooraf geverifieerde
> scriptvariant onder `$HOME/domains/update_wordpress.sh` van elk aantoonbaar
> beheerd Hostinger-account, **buiten** alle `public_html`-installaties.
> Behoud op Hostinger 2 minstens de zes in
> `config/wordpress-migration-policy.json` vastgelegde plugin-exclusies.
> Vergelijk vóór installatie de live scriptinhoud, bestaande per-host-configuratie,
> actieve WordPress-installaties, PHP/WP-CLI-versies, bestaande locks en
> server-/cacheafhankelijkheden. Overschrijf nooit onbekende bestaande scripts.
> Voer per account een alleen-lezen SSH-preflight, een installatie-dry-run,
> een versievergelijking, atomische uitrol en een checksum/syntax-readback uit.
> Stop bij inconsistenties. Start geen WordPress-updates tijdens de migratie.
> Maak geen nieuwe back-uptaken; verifieer bestaande Hostinger-herstelpunten.

## Fase A — bronnen en SSH-inventaris (geautomatiseerd)

- Source of truth: de **live** Hostinger 1-versie; oude Library-bestanden zijn
  alleen vergelijking. De op 10 oktober 2026 gemeten SHA-256 van het live
  Hostinger 1-script was:
  `68e690f00cda62c5e21a513ed3aab42c1ea67191ca2d627be6e9d82823416beb`.
  Dit is geen eeuwige pin; controleer de actuele SHA.
- Historische Hostinger 2-versie `$HOME/update_wordpress_exclusion.sh`:
  SHA-256 `86b104f5107e2a69e70377b99328014d1e2401c7dca9c28ff3553aff211ac13f`.
  **De actuele remote SHA kan hiervan afwijken**.
- De zes Hostinger 2-plugin-slugs zijn verplicht te behouden:
  `cf7-conditional-fields`, `cf7-multi-step`,
  `contact-form-7`,
  `drag-and-drop-multiple-file-upload-contact-form-7`,
  `open-rdw-kenteken-voertuiginformatie`, `wpcf7-redirect`.
  Bijkomende live-exclusies hebben voorrang boven de historische lijst.
- GitHub Actions-workflow `hostinger-wordpress-migration-audit.yml` inventariseert
  **alleen-lezen** de historisch bekende accounts `hostinger-1` t/m
  `hostinger-6`. Het rapporteert hashes, aantallen, Bash-syntaxstatus en de Hostinger 2-vergelijking.
  Daarna volgt een begrensde zoektocht naar de historische exclusiehash buiten publieke webroots.
  De scripts worden **niet** naar GitHub-artifacts geüpload.
- De GitHub-workflow biedt keuzewaarden t/m `hostinger-10`, maar de vier
  laatste omgevingen zijn niet als echte Hostinger-accounts bevestigd.
  Maak daar niet automatisch lege nieuwe Environment-configuraties voor aan.

## Fase B — per-host compatibiliteit en uitzonderingen

- Vergelijk het **volledige** actuele Hostinger 1-script met de live Hostinger 2-
  uitzonderingsvariant. Bewaak hardgecodeerde accountnamen/paden/domeinen,
  variabelen, symlinks, tokenbestanden, externe API-calls, cron en monitoring.
- Verifieer per account dat het script alle *bedoelde* WP-installaties ontdekt.
  Hostinger 1 heeft 30 standaardinstallaties en daarnaast drie afzonderlijke
  WordPress-subinstallaties met bereikbare databases. Die mogen niet blind
  worden overgeslagen.
- Verifieer Hostinger 2-exclusies in de **uitvoeringscode**, niet alleen in
  comments. Het normale WP-CLI-patroon is
  `wp plugin update --all --exclude=slug1,slug2`.
  WordPress-restupdatechecks moeten de bewust uitgesloten plugins afzonderlijk
  rapporteren in plaats van ze als onverwachte 'mislukte updates' te tellen.
- Bestaande extra per-site-exclusies of verschillende PHP-eisen mogen niet
  worden vervangen door een lege default.

## Fase C — voorbereidende uitrol, niet automatisch

- Bepaal pas **na** bewijs uit de echte servers of één portable script of
  meerdere hostspecifieke varianten vereist zijn.
- Behandel scriptinhoud als mogelijk gevoelig: kopieer een live script nooit
  ongecontroleerd naar een publieke repository of openbaar Actions-artifact.
- Iedere per-host-installatie vereist een exact geverifieerd bronbestand,
  unieke doelomgeving en expliciete autorisatie. Laat onbekende bestaande
  scripts intact. Stop bij mismatch, fout of ontbrekende herstelmogelijkheid.
- Plaats alleen het goedgekeurde script onder `$HOME/domains`, nooit in
  `domains/<domein>/public_html`. Verifieer Bash-syntax, SHA-256,
  beschermde uitgesloten plugin-slugs, bestaande lock/staging en permissies.

## Fase D — readback en acceptatie

- Controleer per account versie/hash, syntax, bedoelde WordPress-sites en
  behoud van alle uitsluitingen. Pas na expliciete productieacceptatie komt
  de aparte bestaande WordPress-bulkupdateworkflow in beeld.
- Tijdens scriptmigratie: **geen** WordPress core-, plugin-, thema-, database-
  of cacheupdates; **geen** backupopdrachten; **geen** per-account cronjob.
- Groen in GitHub CI is geen bewijs dat scripts live zijn geïnstalleerd.
  Bewijs van een geslaagde SSH-audit is ook **geen** bewijs van migratie.

## Statusregel

- `AUDIT_OK`: bestaande situatie uitgelezen, **niet gekopieerd**.
- `BLOCKED`: ontbrekende SSH-credentials, afwijkende exclusiehash,
  onveilige/onleesbare scripts of onduidelijke inventaris.
- `MIGRATION_INSTALLED`: alleen gebruiken na afzonderlijk aantoonbare
  daadwerkelijke uitrol **en** succesvolle live readback; deze audit-workflow
  mag dit label nooit produceren.

## Bewijs na live SSH-controles — 10 oktober 2026

Bronnen: [eerste matrixrun](https://github.com/Yolol100/onderhoud/actions/runs/38054364807),
[verdiepte run](https://github.com/Yolol100/onderhoud/actions/runs/38055145091)
en [CI op main](https://github.com/Yolol100/onderhoud/actions/runs/38055145199).

| Hostinger | Laatste aantoonbare status | Migratieacceptatie |
| --- | --- | --- |
| 1 | `domains/update_wordpress.sh` bestaat en Bash-syntax is geldig; 33 domeinmappen; geen `/home/u...`-paden gedetecteerd | Live broninhoud nog **niet** geëxporteerd of op compatibiliteit beoordeeld |
| 2 | 49 domeinmappen; geen script op drie bekende standaardpaden; tweede, begrensde legacy-SHA-zoektocht vond **nul overeenkomsten** | **Geblokkeerd**: de zes historische exclusies zijn wel lokaal vastgelegd, maar niet tegen actuele scriptinhoud geverifieerd |
| 3 | Bestaand `domains`-script, geldige syntax; 37 domeinmappen | Eigen configuratie en mogelijke extra uitzonderingen eerst beoordelen |
| 4 | Bestaand `domains`-script met **dezelfde SHA** als Hostinger 3, maar een **andere domein-inventarisfingerprint** | Niet aannemen dat omgevingen uitwisselbaar zijn; doelaccount per omgeving verifiëren |
| 5 | `domains/update_wordpress.sh` bestaat, maar **faalt Bash-syntaxcontrole**; 26 domeinmappen | **Geblokkeerd**: bestaand script niet overschrijven zonder inhoudsanalyse/herstel |
| 6 | Bestaand `domains`-script, geldige syntax; 2 domeinmappen | Eigen configuratie en sitegerichte historische uitzonderingen onderzoeken |

De Hostinger 2-job had in de eerste poging SSH-afsluitcode 255; de geslaagde verbinding in de tweede poging leverde hierboven genoemde nul-matches op. De totaalscore van de matrix blijft **rood door terecht geblokkeerde doelomgevingen**; een rode audit betekent niet dat een updater op de server gedraaid heeft.

### Exclusions: verplicht maar niet live bewezen

Hostinger 2 heeft de zes historische uitsluitingen in
`config/wordpress-migration-policy.json` en tests opgenomen. Het behoud
van die slugs in een toekomstig **daadwerkelijk uitgevoerd** script is nog
niet aangetoond. De audit controleert geen individuele pluginversies.

### Minimale beslissingen vóór scriptuitrol

1. Vergelijk de **actuele live inhoud** van Hostinger 1 met de genoemde SHA,
   zonder die ongecontroleerd in deze openbare GitHub-repository of Actions-
   artifacts te plaatsen. Controleer externe API- en tokens-afhankelijkheden.
2. Controleer of Hostinger 2 nog andere uitsluitingen heeft en bevestig het
   correcte SSH-account. Gebruik de zes oude uitsluitingen als minimum.
3. Inspecteer de bestaande code/exclusies van Hostinger 3–6, met name de
   syntaxfout op Hostinger 5 en eventuele sitespecifieke pluginpins.
4. Kies daarna pas passende per-host-bronbestanden, voer dry-run/diff uit,
   installeer onder `$HOME/domains` met atomische vervanging **na
   gecontroleerde toestemming/herstelroute**, en lees SHA/syntax terug.
   Geen WordPress-update starten tijdens de scriptmigratie.

**Huidige status:** de migratiecontrole en exclusionsregistratie staan op
`main`. **Geen** updatescripts zijn naar Hostinger 2–6 gekopieerd of
overschreven; geen WordPress-sites, caches of back-ups zijn gewijzigd.
