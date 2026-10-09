# Hostinger 1 opnieuw verbinden met GitHub

Deze handleiding begint bij **hostinger-1**. De andere pakketten krijgen later
hun eigen opeenvolgende GitHub Environments: `hostinger-2`, `hostinger-3`,
enzovoort. Het IP-adres en de SSH-gebruikersnaam zijn accountgegevens en worden
niet in de openbare repository vastgelegd.

## 1. Nieuwe SSH-sleutel op Windows

Open PowerShell:

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\hostinger_onderhoud_1" -C "github-hostinger-1"
```

Druk twee keer op Enter voor een lege passphrase, zodat GitHub Actions
onbeheerd met de sleutel kan inloggen. Overschrijf geen bestaand bestand.
Voeg uitsluitend de **publieke** sleutel toe bij Hostinger **Hosting deel 1 →
SSH Access → Add SSH key**:

```powershell
Get-Content "$env:USERPROFILE\.ssh\hostinger_onderhoud_1.pub" | Set-Clipboard
```

De naam in hPanel wordt `github-hostinger-1`.

## 2. Test op Windows

Haal de actuele SSH-host, SSH-gebruiker en poort op uit **Hosting deel 1 → SSH
Access** in hPanel. Gebruik je nieuwe privésleutel met `ssh -i`. Controleer
de SSH-**server**fingerprint via een onafhankelijk Hostinger-kanaal vóór de
eerste vertrouwensbevestiging.

Controleer vervolgens wachtwoordloze toegang en `rsync`:

```powershell
ssh -o BatchMode=yes -o PasswordAuthentication=no -o IdentitiesOnly=yes -p POORT -i "$env:USERPROFILE\.ssh\hostinger_onderhoud_1" GEBRUIKER@HOST "command -v rsync && echo SSH_KEY_OK"
```

Vervang `POORT`, `GEBRUIKER` en `HOST` door de gegevens uit hPanel.
Bij `SSH_KEY_OK` zijn de lokale SSH-sleutel en rsync in orde.

## 3. GitHub Environment aanmaken

Open https://github.com/Yolol100/onderhoud/settings/environments

Maak de omgeving `hostinger-1` aan. Voeg daarin drie **Environment secrets**
toe, ieder via **Add environment secret**. Plak deze waarden uitsluitend in GitHub.

### HOSTINGER_SSH_PRIVATE_KEY

Kopieer de nieuwe **privé**sleutel rechtstreeks van je eigen pc naar het
GitHub Secret:

```powershell
Get-Content "$env:USERPROFILE\.ssh\hostinger_onderhoud_1" -Raw | Set-Clipboard
```

### HOSTINGER_SSH_KNOWN_HOSTS

Na **onafhankelijke verificatie** van de Hostinger-serverfingerprint kun je de
juiste openbare serverhostkey-regel ophalen (vervang de placeholders):

```powershell
ssh-keygen -F "[HOST]:POORT" -f "$env:USERPROFILE\.ssh\known_hosts" | Where-Object { $_ -notmatch '^#' } | Set-Clipboard
```

De **serverhostkey** is niet dezelfde sleutel als je eigen `.pub`-bestand.

### HOSTINGER_SITES_JSON

Gebruik dit JSON-formaat, vervang de drie accountvelden door het exacte
SSH-commando in hPanel:

```json
{
  "version": 2,
  "account": {
    "host": "IP_VAN_HOSTINGER",
    "user": "u123456789",
    "port": 65002
  },
  "sites": {}
}
```

De lege `sites`-lijst is correct: voor de eerste accountbrede
verbindingstest is geen domein of plugin nodig.

## 4. Test GitHub → Hostinger 1

Open https://github.com/Yolol100/onderhoud/actions/workflows/hostinger.yml
en kies **Run workflow**:

- Branch: `main`
- Hosting: `hostinger-1`
- Site: leeg
- Mode: `connect`
- Confirm: leeg

Alleen wanneer de Action `CONNECT OK` toont is de nieuwe verbinding
bevestigd. Er veranderen geen websitebestanden. Mode `list` telt
daarna eventueel de toegankelijke domeinmappen (geen namen in openbare logs).

## 5. Volgende hostingpakketten

Voor **hostinger-2** gebruik je een afzonderlijke sleutel
`hostinger_onderhoud_2` en een **nieuwe** GitHub Environment
`hostinger-2`, met precies dezelfde drie secretnamen maar andere waarden.
Doe hetzelfde voor de volgende nummers. Verwissel nooit de sleutel/IP/gebruiker
van twee pakketten.

Bestaande GitHub Environments met eerdere namen worden niet automatisch
hernoemd of verwijderd; verwijder/vervang die pas bewust na een
verbindingscontrole van de nieuwe omgeving.

## Beperkingen

Dit is SSH-transport naar één Hostinger-account per Environment. Het heeft
alleen rechten die Hostinger aan die SSH-gebruiker geeft. `connect` en
`list` zijn read-only; `preview` en `deploy` blijven beperkt tot
expliciet geregistreerde thema-/pluginmappen. Er worden geen WordPress-updates,
databasewijzigingen, Hostinger-back-ups of cronjobs aangemaakt.

Officiële documentatie:
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/actions/reference/security/secure-use
