# Hostinger SSH - GitHub Actions

Een GitHub-repository voor meerdere afzonderlijke Hostinger-hostingpakketten.
De GitHub Actions-keuzelijst gebruikt consequent `hostinger-1` tot en met
`hostinger-10`; elk pakket heeft zijn eigen GitHub Environment en SSH-sleutel.

## Wat kun je doen?

- **connect**: handmatige, alleen-lezen SSH-test voor één gekozen hostingpakket.
- **list**: telt domeinmappen van dat account zonder domeinnamen te loggen.
- **preview**: simuleert wijzigingen aan een expliciet geregistreerde WordPress
  thema- of pluginmap; wijzigt niets op de server.
- **deploy**: uitsluitend voor een vooraf geregistreerde thema/pluginmap met
  expliciete typed bevestiging en controle achteraf.
- **WordPress bulkupdate - Hostinger 1**: aparte, uitsluitend handmatige
  onderhoudsworkflow voor het bestaande `$HOME/domains/update_wordpress.sh`,
  gevolgd door cache- en basiswebsitecontroles. Lees eerst
  [WordPress-onderhoud](docs/WORDPRESS-ONDERHOUD.md).

Geen cronjobs, nieuwe back-upjobs, willekeurige SSH-/SQL-commando's of
geautomatiseerde updates op andere hostingnummers. Het bestaande serverscript
blijft onafhankelijk: zijn inhoud moet vooraf worden gecontroleerd. Hostinger
beheert eventuele providerback-ups; de workflow verifieert ze niet.

## Opnieuw beginnen

Zie [Installatie: Hostinger 1](docs/INSTALLATIE.md). Maak eerst een GitHub
Environment `hostinger-1` met **drie eigen Environment Secrets**:
`HOSTINGER_SSH_PRIVATE_KEY`, `HOSTINGER_SSH_KNOWN_HOSTS`,
`HOSTINGER_SITES_JSON`.

De werkelijke SSH-server, gebruikersnaam en sleutelgegevens blijven buiten
de openbare repository. `HOSTINGER_SITES_JSON` bevat versie 2 met één
`account` per GitHub Environment en optioneel een `sites`-register.
Een lege `sites`-lijst is voldoende voor de read-only verbindingstest.

## Veiligheidsgrenzen

- Secrets alleen in GitHub Environments, niet in de repository of chat.
- Hostkeys altijd onafhankelijk met Hostinger verifiëren.
- Per hostingpakket een afzonderlijke SSH-sleutel en Environment.
- Test `connect` vóór de eerste `list`; geen wijzigingen aan websites.
- Maak de repository privé voordat je klantcode of niet-openbare thema's toevoegt.
- Nieuwe workflows/tests bewijzen geen live SSH-verbinding totdat `CONNECT OK`
  op het gekozen pakket in GitHub Actions is bevestigd.
- WordPress-bulkupdate uitsluitend via het aparte Hostinger-1-workflowbestand,
  op `main` en na invoer van `UPDATE:hostinger-1:ALL`.