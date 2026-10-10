# WordPress-onderhoud op Hostinger 1 — handmatig, gecontroleerd

Deze GitHub Actions-workflow gebruikt **alleen** de bestaande Hostinger-1 Environment-secrets en het al aanwezige script `$HOME/domains/update_wordpress.sh`. De algemene `hostinger.yml` blijft voor SSH-connect/list/preview/deploy bestaan. Er wordt **geen extra back-up gemaakt**, geen serverbestand vervangen en geen automatische cron/schedule toegevoegd.

## Stap 1 — alleen-lezen preflight

Open [WordPress bulkupdate - Hostinger 1](https://github.com/Yolol100/onderhoud/actions/workflows/wordpress-onderhoud-hostinger-1.yml), kies `main`, `Run workflow`, `action: preflight`. Laat `confirm`, `script_sha256` en `inventory_sha256` leeg.

De preflight controleert SSH, het bestaan en de Bash-syntax van het vaste updatescript, het aantal herkenbare WordPress-installaties, databasebereikbaarheid, de standaard webroot-structuur, de WP-home-domeinen en multisite-detectie. Het bestaande script wordt **niet** gestart. Kopieer de twee SHA-256-waarden (script en inventaris) uit een **groene** preflight.

**Belangrijk:** preflight bewijst niet wat het externe serverscript precies zal doen. Controleer de actuele scriptinhoud en de beschikbaarheid van een Hostinger-herstelpunt voordat een productie-update wordt vrijgegeven. Dit project maakt zelf geen back-ups; het garandeert ook geen herstel.

## Stap 2 — alle installaties bijwerken

Start dezelfde workflow opnieuw met deze exacte inputs:

- `action`: `update`
- `confirm`: `UPDATE:hostinger-1:ALL`
- `script_sha256`: de **64 tekens** van `Bestaand updatescript (SHA-256)` uit preflight
- `inventory_sha256`: de **64 tekens** van `WordPress-inventaris (SHA-256)` uit **dezelfde** preflight

Als het updatescript of de herkende installaties tussen preflight en update zijn gewijzigd, **stopt de workflow vóór het uitvoeren van de updater**. Een gewijzigde/mislukte inventaris, onbekende WordPress-mapstructuur, WordPress Multisite of niet-passend `home`-domein wordt niet stilzwijgend als geslaagd beoordeeld. Die situatie vraagt om een aangepaste sitegerichte aanpak.

Daarna gebruikt de workflow **het bestaande script eenmaal**, met werkmap `$HOME/domains`. Wat het script daadwerkelijk bijwerkt (core, plugins, thema's, database, talen, eventuele externe cache of eigen back-ups) moet eerst uit de *actuele live inhoud* blijken. De workflow voegt geen nieuwe update- of back-upcommando's aan dat bestaande script toe.

## Stap 3 — cache en controle

De runner voert **na** de updater, ook bij een niet-nul exitcode:

1. `wp cache flush` per herkende WordPress-installatie (objectcache).
2. `wp litespeed-purge all` als LiteSpeed Cache actief is.
3. `wp rocket clean --confirm` als WP Rocket actief is (of een bewaakte bestaande API-fallback).
4. WordPress- en databaseversie-runtimechecks en gecontroleerde WP-CLI-update-inventaris voor core, plugins, thema's en geïnstalleerde vertalingen. Wordt een update gemist, is een check ongeldig of bevat het log duidelijke PHP-/updater-foutsignaturen, dan is de workflow **rood**.
5. Publieke HTTPS-homepages met een basiscontrole op HTTP 200, niet-lege HTML-respons en bekende fatale fouten; redirects mogen alleen op het oorspronkelijke domein/`www` uitkomen.

Ruwe serveruitvoer en details staan uitsluitend in `$HOME/.wordpress-maintenance-logs/update-*.log` met bestandsrechten `0600`. Publieke Actions-logs bevatten alleen aantallen, statussen en goedkeuringshashes; er wordt geen klantdomeinlijst getoond. Een code-/CI-success vervangt geen echte productie-QA.

### Grenzen die expliciet openblijven

- **Hostinger servercache, Hostinger CDN, externe CDN's en PHP OPcache** zijn aparte lagen. De nieuwe runner heeft hiervoor geen providerautorisatie en kan hun purge **niet** bevestigen. Het oude serverscript doet dit mogelijk al; valideer dit apart in Hostinger. Claim niet dat *alle* cachelagen zeker leeg zijn zonder bewijs.
- De WordPress-restupdatecontrole omvat alleen updates die de lokale WP-CLI/WordPress-provider kan detecteren. Private licenties, betaalde pluginportalen, WooCommerce-databasemigraties en hostinstellingen kunnen andere controles vereisen.
- Multisite, afwijkende mappen, aliasdomeinen en pad-gebaseerde home-URL's **blokkeren** de bulkupdate totdat er een bewezen alternatief beschikbaar is. Beter gecontroleerd stoppen dan een deels gemiste update groen markeren.
- De publieke smoke-test bewijst niet dat contactformulieren, gebruikerslogins, WooCommerce-checkouts, webhooks, e-mail of mobiele interfaces werken. Test de kritieke flows afhankelijk van de aanwezige websites.
- Controleer Hostinger's herstelpunt vóór gebruik. **Geen backup/restore-actie** is in deze workflow voorzien.

## Misgelopen update

Stop bij rode `preflight` of `update`. Start het bestaande updatescript **niet** opnieuw zonder foutanalyse. Lees het privé-serverlog op Hostinger, vergelijk site-/cache-/versiestatussen, onderzoek concrete fouten en gebruik alleen een geverifieerd herstelpunt of een gerichte herstelactie. Geen automatische retry of rollback.

## Primair geraadpleegde technische documentatie

- [WP-CLI core check-update](https://developer.wordpress.org/cli/commands/core/check-update/)
- [WP-CLI plugin list](https://developer.wordpress.org/cli/commands/plugin/list/)
- [WP-CLI theme list](https://developer.wordpress.org/cli/commands/theme/list/)
- [WP-CLI core update-db](https://developer.wordpress.org/cli/commands/core/update-db/)
- [LiteSpeed CLI](https://docs.litespeedtech.com/lscache/lscwp/cli/)
- [WP Rocket CLI](https://docs.wp-rocket.me/article/1497-wp-cli-interface-for-wp-rocket)
- [Hostinger cachelagen](https://www.hostinger.com/support/6215624-how-to-use-cache-manager-at-hostinger/)
- [GitHub Actions environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)
