# WordPress-onderhoud Hostinger 1 (handmatig)

Deze workflow is een **aparte, handmatig gestarte** onderhoudsactie in
`Yolol100/onderhoud`; de bestaande `hostinger.yml` voor connect/list/preview/deploy
blijft ongewijzigd. Alleen GitHub Environment `hostinger-1` wordt gebruikt.

## Eén keer eerst controleren

Open [WordPress bulkupdate - Hostinger 1](https://github.com/Yolol100/onderhoud/actions/workflows/wordpress-onderhoud-hostinger-1.yml)
via **Actions → Run workflow**, branch `main`:

1. Kies `action: preflight` en laat `confirm` leeg.
2. Controleer dat `PREFLIGHT OK` verschijnt, hoeveel WordPress-installaties
   gevonden worden en welke SHA-256 van het bestaande script gemeld wordt.
3. Controleer in Hostinger dat het bestaande script onder
   `$HOME/domains/update_wordpress.sh` staat, de gewenste sites bijwerkt en
   geen ongewenste bijkomende acties uitvoert. Het script wordt **niet** door
   GitHub aangemaakt of geüpload.
4. Controleer bij Hostinger zelf de herstelmogelijkheid. De workflow maakt
   **geen** backups, controleert providerbackups niet en kan een mislukte
   WordPress-update niet automatisch terugdraaien.

## De volledige update starten

Via dezelfde knop **Run workflow** op `main`:

- `action`: `update`
- `confirm`: `UPDATE:hostinger-1:ALL`

Het onderhoud verloopt achtereenvolgens:

1. De bestaande hostinger-1-SSH-secrets en strikt geverifieerde hostkey worden
   gebruikt. Alleen `$HOME/domains/update_wordpress.sh` mag uitgevoerd worden.
2. De bestaande updater wordt eenmaal gestart. De daadwerkelijke core-,
   thema-, plugin-, taal- en database-updates zijn afhankelijk van **wat het
   bestaande serverscript op dat moment implementeert**.
3. Daarna wordt de WordPress-objectcache van de herkende installaties geleegd,
   en de caches van **actieve** LiteSpeed Cache / WP Rocket plugins. Een fout
   in een cache-actie maakt het eindresultaat rood.
4. Daarna worden WordPress-bootstrap/runtime en publieke HTTPS-homepages
   gecontroleerd. Een fout, een gewijzigd aantal WordPress-sites of een
   niet-nul afsluitcode van de updater laat de workflow falen.

### Privacy en foutopsporing

- Er staan geen servergegevens, privésleutels of klantdomeinen in de repo.
- GitHub logs tonen aantallen, een script-hash en foutstatus, geen domeinnamen.
- De **ruwe output van de bestaande updater** en WP-CLI staat alleen op
  Hostinger bij `$HOME/.wordpress-maintenance-logs/update-*.log` (mode 0600).
- De nieuwe workflow maakt geen backups en wijzigt geen cron, PHP-, DNS- of
  Hostinger-instellingen. De **bestaande updater** kan onafhankelijk meer doen;
  controleer dat script eerst voordat je `update` start.
- Een groene basis-HTTPS-check zegt niet dat checkout, formulieren, inloggen,
  tracking of e-mail volledige regressietests hebben doorstaan.
- Een WordPress-cacheflush is **niet** hetzelfde als een Hostinger server/CDN-
  of externe proxy-purge. De nieuwe workflow kan die lagen niet zelfstandig
  verifiëren. Als het bestaande serverscript die beheert, moet dat apart via
  Hostinger worden gecontroleerd. Claim dus niet dat *alle* caches zeker weg zijn.

### Grenzen

- Geen schedule, push-trigger, vrije shellinvoer, andere hostingnummers of
  automatische website-updates zonder handmatige typed bevestiging.
- Geen back-up- of restoretaak in deze GitHub-workflow.
- Alleen WordPress-roots direct onder `$HOME/domains/*/public_html` worden door
  de nacheck ontdekt. Andere structuren moeten handmatig gecontroleerd worden.
- Publieke gezondheidscontrole gebruikt HTTPS en kan sites achter onderhouds-
  of toegangsbeveiliging als fout markeren.
