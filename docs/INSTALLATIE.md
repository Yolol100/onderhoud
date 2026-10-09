# Handleiding: GitHub verbinden met Hostinger

Hiermee kan GitHub automatisch een SSH-verbinding maken wanneer jij dat
handmatig start. Je hoeft geen plugin, Go-server of extra MCP te installeren.
Er zijn geen automatische website-updates, back-ups of onderhoudsscripts.

## 1. Zet SSH aan op Hostinger

- Hostinger hPanel -> Websites -> Dashboard -> SSH Access -> Enable.
- Noteer SSH-host of IP-adres, SSH-gebruikersnaam en SSH-poort.
- Voor veel Web/Cloud-pakketten is de poort 65002; controleer die in hPanel.
- SSH/rsync moeten door je hostingpakket worden ondersteund.

## 2. Maak een losse SSH-sleutel

Op je eigen computer met OpenSSH:

    ssh-keygen -t ed25519 -f hostinger_onderhoud -N "" -C "github-onderhoud"

- Voeg ALLEEN hostinger_onderhoud.pub toe bij hPanel -> SSH Access -> Add SSH key.
- Bewaar hostinger_onderhoud (zonder .pub) vertrouwelijk; zet hem NOOIT in Git.
- Deze aparte, niet-met-wachtzin beveiligde sleutel wordt alleen door het
  afgeschermde GitHub Actions Secret gebruikt.

## 3. Controleer de serveridentiteit

- Haal de publieke SSH-hostkey op voor host/IP + poort.
- Vergelijk de fingerprint met een onafhankelijk bevestigde serverfingerprint,
  bijvoorbeeld via een vertrouwd Hostinger-kanaal.
- Zet pas daarna de volledige geverifieerde known_hosts-regel in GitHub.
- Bij niet-standaardpoort heeft die de vorm:
  [SSH_HOST]:POORT ssh-ed25519 DE_PUBLIEKE_HOST_SSH_KEY
- Blind een resultaat van ssh-keyscan vertrouwen is onvoldoende.

## 4. Zet in GitHub drie geheime waarden

Repository -> Settings -> Environments -> New environment -> hostinger.
Voeg onder Environment secrets toe:

- HOSTINGER_SSH_PRIVATE_KEY = volledige inhoud van hostinger_onderhoud (privé).
- HOSTINGER_SSH_KNOWN_HOSTS = geverifieerde known_hosts-regel.
- HOSTINGER_SITES_JSON = onderstaande JSON met jouw echte site(s).

Voorbeeldstructuur van HOSTINGER_SITES_JSON:

    {
      "version": 1,
      "sites": {
        "mijn-thema": {
          "host": "123.123.123.123",
          "user": "u123456789",
          "port": 65002,
          "domain": "example.com",
          "type": "theme",
          "slug": "demo-theme",
          "health_url": "https://example.com/"
        }
      }
    }

- Site-ID = de naam onder sites, hier mijn-thema.
- type is uitsluitend theme of plugin.
- De gekozen plugin/thema-map op Hostinger moet al bestaan.
- De doelmap wordt automatisch opgebouwd:
  /home/USER/domains/DOMEIN/public_html/wp-content/themes/SLUG
  of /home/USER/domains/DOMEIN/public_html/wp-content/plugins/SLUG
- Het script kan maximaal 25 sites registreren. Gebruik per hostingaccount
  een eigen SSH-sleutel en een afzonderlijke Action/omgeving indien nodig.
- Beperk de omgeving bij voorkeur tot main en stel waar mogelijk goedkeuring in.
- Als Environment secrets niet beschikbaar zijn bij je GitHub-plan, kun je
  repository secrets gebruiken, maar controleer het beveiligingsbeleid.

## 5. Doe eerst een verbindingscontrole

- GitHub -> Actions -> Hostinger SSH - handmatig -> Run workflow.
- site = mijn-thema (of jouw gekozen site-ID).
- mode = connect. Geen payload nodig en geen bestanden gewijzigd.
- Maak daarna alleen een maptak payload/mijn-thema met de gewenste code.
- WordPress-thema heeft een style.css nodig.
- WordPress-plugin heeft een PHP-hoofdbestand op hoofdniveau nodig.
- mode = preview: toont de bestandsverschillen zonder te schrijven.
- mode = deploy: typ in confirm exact DEPLOY:mijn-thema.
- Het script voert checksumvergelijking en basis HTTPS-controle uit.

## Heel belangrijk

- Deze repo was bij aanmaak OPENBAAR. Maak hem prive voordat je eigen
  klantcode, websites of andere vertrouwelijke bestanden commit.
- Er is geen geplande/publicatie-op-push actie. Alleen jij start de workflow.
- Geen --delete: extra bestaande serverbestanden blijven behouden.
- SSH-commando's kunnen niet door vrije tekst uit GitHub worden bepaald.
- Geen SQL, database, WordPress-updates, back-ups, rollbackautomatisering of
  serverinstellingen. Die activiteiten staan buiten deze repo.
- De bestaande Hostinger-back-ups worden niet gewijzigd. Controleer zelf
  of het laatst beschikbare herstelpunt aanwezig en bruikbaar is.
- Test op staging als dat kan. Check na een deploy ook WooCommerce checkout,
  pluginactivatie, themaweergave en Elementor als van toepassing.
- Bij fouten stopt de Action. Er wordt niet blind opnieuw gepubliceerd.

## Officiele bronnen

- https://support.hostinger.com/en/articles/1583645-how-to-enable-ssh-access
- https://support.hostinger.com/en/articles/5634532-how-to-generate-ssh-keys-and-add-them-to-hpanel
- https://www.hostinger.com/support/how-to-use-rsync-to-sync-files-and-directories-at-hostinger/
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/actions/reference/security/secure-use
