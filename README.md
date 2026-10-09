# Hostinger SSH - GitHub Actions

Deze aparte repository maakt een gecontroleerde verbinding tussen GitHub
Actions en Hostinger voor geselecteerde WordPress thema- en pluginbestanden.

Geen MCP, geen Go-server, geen geplande updates, geen onderhoud, geen cron
en geen nieuwe back-upautomatisering. Hostinger-back-ups blijven ongewijzigd.

## Hoe werkt het?

1. GitHub Actions handmatig starten met mode connect (controle SSH).
2. Daarna preview (rsync dry-run zonder serverwijzigingen).
3. Alleen na goedkeuring deploy met tekst DEPLOY:site-ID.
4. Checksums na upload vergelijken en website daarna zelf beoordelen.

De sitekeuze staat alleen in HOSTINGER_SITES_JSON (GitHub Secret).
SSH privésleutel en geverifieerde hostkey staan eveneens in Secrets.
De code ondersteunt alleen exact geregistreerde WordPress thema/plugin
directories en geen willekeurige remote shell of databasecommando's.
Bestaande bestanden worden niet automatisch verwijderd.

## Begin hier

[Installatie in eenvoudige stappen](docs/INSTALLATIE.md)

### Inhoud
- .github/workflows/hostinger.yml - alleen handmatig vanaf main
- .github/workflows/ci.yml - test bij commits zonder SSH/secrets
- scripts/hostinger.py - inputvalidatie, SSH, rsync, readback, HTTPS
- tests/test_hostinger.py - veiligheids- en regressietests
- config/sites.example.json - uitsluitend fictieve waarden
- AGENTS.md - vaste repositorygrenzen
- payload/<site-ID>/ - voeg zelf deploybare bestanden toe na verificatie

## Status

De repository is bij aanmaak openbaar. Maak hem privé voordat je
vertrouwelijke (klant)code toevoegt. Er zijn geen echte Hostinger secrets
ingesteld en er is nog geen live SSH/websitecontrole uitgevoerd.
