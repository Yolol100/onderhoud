# GitHub koppelen aan ALLE websites binnen één Hostinger-hostingaccount

Je hebt al bevestigd dat je vanuit Windows via SSH met Hostinger kunt
inloggen zonder wachtwoord en dat \`rsync\` beschikbaar is. Je hoeft geen
aparte SSH-sleutel per domein aan te maken. De SSH-toegang geldt alleen
voor de websites/mappen waarop die Hostinger-gebruiker rechten heeft.

Er komen geen automatische updates, onderhoudsscripts, cronjobs of back-ups bij.

## 1. Open de GitHub-instellingen

Ga naar https://github.com/Yolol100/onderhoud/settings/environments

Maak een Environment aan met exact de naam **hostinger**. Kies binnen
Environment secrets voor **Add secret**.

## 2. Geheim 1: HOSTINGER_SSH_PRIVATE_KEY

Open **Windows PowerShell** en voer uit:

    Get-Content "$env:USERPROFILE\.ssh\hostinger_onderhoud" -Raw | Set-Clipboard

Plak de geheime SSH-sleutel uitsluitend als waarde van GitHub Environment
Secret \`HOSTINGER_SSH_PRIVATE_KEY\`. Zet deze nooit in een GitHub-bestand,
issue of ChatGPT-gesprek.

## 3. Geheim 2: HOSTINGER_SSH_KNOWN_HOSTS

Controleer eerst de Hostinger-serverfingerprint via een onafhankelijk
vertrouwd Hostinger-kanaal. Haal dan de geverifieerde known_hosts-regel op
in Windows PowerShell:

    ssh-keygen -F "[81.16.31.38]:65002" -f "$env:USERPROFILE\.ssh\known_hosts" |
      Where-Object { $_ -notmatch '^#' } | Set-Clipboard

Plak dit bij GitHub Environment Secret \`HOSTINGER_SSH_KNOWN_HOSTS\`.
De hostkey is NIET dezelfde als je eigen SSH-key.

## 4. Geheim 3: HOSTINGER_SITES_JSON

**Je hoeft GEEN domeinnaam te kiezen om de hele hosting te controleren.**

Voeg onder Environment secrets een derde secret toe met de naam
\`HOSTINGER_SITES_JSON\` en deze inhoud:

    {
      "version": 2,
      "account": {
        "host": "81.16.31.38",
        "user": "u919867035",
        "port": 65002
      },
      "sites": {}
    }

Hiermee koppel je één hostingaccount. \`sites\` mag leeg blijven voor
\`connect\` en \`list\`. Later kun je per website een specifiek doel
registreren voor beperkte uploads. Je hoeft daarvoor geen nieuwe SSH-key.

## 5. Test de gehele hosting via GitHub

Ga naar https://github.com/Yolol100/onderhoud/actions/workflows/hostinger.yml
Klik **Run workflow** en kies:

- Branch: main
- Site: leeg laten
- Mode: connect
- Confirm: leeg laten

Groene melding \`CONNECT OK\` betekent dat GitHub veilig verbinding maakt
met het Hostinger-account en rsync aanwezig is. Er verandert niets.

Start daarna eventueel nog eens met **mode list**. Dat telt de
bereikbare domeinmappen onder \`~/domains\`, maar laat vanwege de
openbare GitHub-logs geen namen zien. Dit is niet hetzelfde als
automatisch alle websites en webshops beheren.

## 6. Later: 1 website gericht bijwerken (optioneel)

Voor \`preview\` en \`deploy\` voeg je een target toe onder \`sites\`:

    {
      "version": 2,
      "account": {
        "host": "81.16.31.38",
        "user": "u919867035",
        "port": 65002
      },
      "sites": {
        "mijn-thema": {
          "domain": "example.com",
          "type": "theme",
          "slug": "demo-theme",
          "health_url": "https://example.com/"
        }
      }
    }

Vervang \`example.com\` en \`demo-theme\` door je werkelijke
WordPress-domein en bestaande themamap. Het uploadpad wordt opgebouwd als
\`/home/<SSH-gebruiker>/domains/<domein>/public_html/wp-content/themes/<slug>\`.
Bij \`plugin\` is het pad onder \`wp-content/plugins\`.

Zet de geselecteerde code in \`payload/mijn-thema/\`.
Run eerst **preview**. Run daarna alleen op jouw verzoek **deploy**
met bevestiging \`DEPLOY:mijn-thema\`. Er worden geen bestanden verwijderd.
Test kritieke WordPress-/WooCommerce-functionaliteit eerst op staging.

## Beperkingen

- \`connect\` en \`list\` zijn alleen controles, zonder schrijfacties.
- Eén SSH-account kan meerdere sites zien, maar geen onbegrensde root
  of hPanel-eigendomsrechten. Andere hostingaccounts vragen apart toegang.
- Geen vrije servercommando's en geen onbeveiligde bestandswijzigingen.
- Hostinger beheert eigen back-ups. Deze repo automatiseert dat niet.
- De repo is op dit moment openbaar: publiceer geen geheime sitebestanden.

Meer info: https://support.hostinger.com/en/articles/1583245-how-to-connect-to-a-hosting-plan-via-ssh
GitHub Secrets: https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
