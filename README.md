# OCR Bot — Clash of Clans (headless via ADB)

**Versione:** 1.7 (vedi `VERSION` in cima a `BOT_COMPLETO_MAC.py`)

Bot in Python che automatizza il farming in Clash of Clans su BlueStacks (Mac), completamente **in background**: pilota l'emulatore Android via ADB (screenshot + tap/swipe), non lo schermo reale del Mac. Questo significa che BlueStacks può restare minimizzato o nascosto — il bot funziona lo stesso, senza bisogno di vedere nulla a schermo.

Invia inoltre notifiche su Telegram all'avvio, alla fine e in caso di interruzione della sessione.

⚠️ **Attenzione**: automatizzare gli attacchi in un gioco può violare i termini di servizio del gioco stesso e portare al ban dell'account. Usalo a tuo rischio e solo se sei consapevole delle conseguenze.

## Come funziona

Ad ogni ciclo (`run_attack()`):

1. Tocca "Attacco!" nel villaggio → tab Multigiocatore → "Trova una partita" → conferma "Attacco!" nella schermata riepilogo esercito.
2. Legge via OCR il **"Bottino disponibile"** (elisir) dell'avversario trovato, nella schermata di scouting prima che parta la battaglia.
   - Se è sopra `THRESHOLD` (default 800.000): procede e aspetta l'inizio della battaglia.
   - Se è sotto soglia: tocca "Avanti" per cercare un altro avversario, fino a `MAX_SKIP_ATTEMPTS` tentativi.
3. Appena la battaglia inizia, schiera **tutte** le truppe e gli eroi disponibili in un unico passaggio, sempre nella stessa zona della mappa (lato destro/basso — quella testata con successo: 93% danno, 2 stelle), poi attiva le abilità degli eroi.
4. Aspetta che la battaglia si svolga (tempo casuale tra `BATTLE_DURATION_WAIT`), poi torna al villaggio.
5. Ripete, fino a `MAX_TRIGGERS` attacchi o `SESSION_DURATION` (default 50 minuti), poi si ferma da solo.

`debug.png` viene sovrascritto ad ogni lettura OCR del bottino con l'immagine post-elaborazione: utile per capire se Tesseract sta leggendo bene la zona giusta.

Ad ogni evento importante (avvio, fine sessione, errori, interruzione manuale) il bot invia un messaggio Telegram.

## Struttura del progetto

```
ocr-bot/
├── BOT_COMPLETO_MAC.py   # script principale
├── requirements.txt      # dipendenze Python
├── cred                  # credenziali Telegram (NON versionato, va creato da te)
├── debug.png              # screenshot di debug OCR (rigenerato ad ogni lettura, NON versionato)
└── venv/                  # virtualenv Python (NON versionato)
```

## Requisiti

- macOS con [BlueStacks](https://www.bluestacks.com/) installato, con Clash of Clans già configurato e loggato
- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract):
  ```bash
  brew install tesseract
  ```
- Un bot Telegram (per le notifiche): crealo con [@BotFather](https://t.me/BotFather) per ottenere il token, e recupera il tuo `chat_id` (es. scrivendo al bot e leggendo `https://api.telegram.org/bot<TOKEN>/getUpdates`)

### Abilitare ADB in BlueStacks

Il bot parla con BlueStacks tramite ADB (Android Debug Bridge), lo stesso protocollo usato per il debug delle app Android. Va abilitato una volta sola:

1. Apri BlueStacks → **Impostazioni** (ingranaggio) → **Avanzate**
2. Attiva **"Android Debug Bridge"**
3. Lascia BlueStacks aperto (può restare minimizzato/in background) quando lanci il bot

Il bot cerca l'eseguibile `adb` prima nel `PATH` di sistema, poi in quello incluso in BlueStacks (`/Applications/BlueStacks.app/Contents/MacOS/hd-adb`), quindi non serve installare Android Studio o altri SDK.

## Configurazione delle credenziali (variabili d'ambiente)

Il token del bot Telegram e il chat_id non sono scritti nel codice: si leggono da variabili d'ambiente, dichiarate in un file `cred` (escluso da git tramite `.gitignore`, quindi resta solo sul tuo computer).

Crea un file `cred` nella cartella del progetto con questo contenuto:

```bash
export TELEGRAM_BOT_TOKEN="il_tuo_token"
export TELEGRAM_CHAT_ID="il_tuo_chat_id"
```

Poi, ogni volta che apri un nuovo terminale, prima di lanciare il bot carica le variabili con:

```bash
source cred
```

Se una delle due variabili manca, lo script si ferma subito con un messaggio d'errore invece di partire senza notifiche configurate.

## Installazione

```bash
# 1. crea il virtualenv e installa le dipendenze
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. crea il file cred con le tue credenziali (vedi sopra)

# 3. avvia BlueStacks e abilita ADB (vedi sopra), poi carica le credenziali e avvia il bot
source cred
python BOT_COMPLETO_MAC.py
```

## Eseguirlo davvero "in background"

Una volta avviato, BlueStacks può restare minimizzato o su un'altra Space: il bot continua a funzionare perché non dipende da cosa è visibile sullo schermo del Mac, solo dalla connessione ADB. Per non dover nemmeno tenere il Terminale aperto in primo piano, puoi lanciarlo con `nohup`:

```bash
source cred
nohup python BOT_COMPLETO_MAC.py > bot.log 2>&1 &
```

Con `nohup`/`&` lo script gira come processo in background: usa `tail -f bot.log` per seguirne l'output, e le notifiche Telegram ti tengono comunque aggiornato su inizio/fine/errori senza dover guardare il terminale.

## Calibrazione delle coordinate

Tutte le coordinate (pulsanti, zona di schieramento, regione OCR del bottino) sono calibrate sullo screenshot ADB di BlueStacks, che è **1920x1080** indipendentemente dalla risoluzione del Mac o dallo scaling Retina (BlueStacks lo riporta internamente come 1080x1920 "ritratto", ma lo screenshot catturato è sempre in landscape 1920x1080).

Se in futuro l'interfaccia del gioco cambia (aggiornamento di Clash of Clans) o vuoi modificare la zona di schieramento, usa la modalità di calibrazione per salvare uno screenshot di riferimento:

```bash
python BOT_COMPLETO_MAC.py --calibrate
```

Questo salva `calibrate.png` (1920x1080): aprilo con un visualizzatore che mostra le coordinate del cursore (es. Anteprima su Mac) per misurare i punti che ti servono, poi aggiorna le costanti in cima al file (`ATTACK_BUTTON`, `DEPLOY_POINTS`, `OCR_REGION`, ecc.).

## Parametri principali

Tutti i parametri configurabili sono in cima al file (`BOT_COMPLETO_MAC.py`):

| Parametro | Significato |
|---|---|
| `THRESHOLD` | Elisir minimo saccheggiabile ("Bottino disponibile") per decidere di attaccare |
| `MAX_SKIP_ATTEMPTS` | Quanti avversari scartare al massimo prima di attaccare comunque l'ultimo trovato |
| `TROOP_SLOTS` / `HERO_SLOTS` | Posizioni x nella barra truppe/eroi in basso da cui vengono selezionati per lo schieramento |
| `DEPLOY_POINTS` | Punti della mappa in cui vengono schierate tutte le truppe (sempre la stessa zona) |
| `BATTLE_START_MAX_WAIT` | Attesa massima che la battaglia inizi dopo aver accettato un avversario |
| `BATTLE_DURATION_WAIT` | Intervallo (min, max) di attesa per lasciar svolgere la battaglia prima di tornare al villaggio |
| `SESSION_DURATION` | Durata massima della sessione (default 50 minuti) |
| `MAX_TRIGGERS` | Numero di attacchi dopo cui il bot si ferma da solo |

## Controllo remoto via Telegram (mini PC + PC Windows)

Per poter avviare il bot da fuori casa senza tenere il Mac acceso, il bot gira invece su un **PC Windows** con BlueStacks, tenuto spento quando non serve e risvegliato al bisogno:

- `windows/run_bot.bat` — script che va sul PC Windows: apre BlueStacks, aspetta che ADB veda il device, avvia Clash of Clans, poi lancia `BOT_COMPLETO_MAC.py`. Lanciato da un **Task Scheduler di Windows** (non da `Start-Process` diretto via SSH: la sessione SSH su Windows lega i processi a un Job Object che li uccide alla disconnessione, mentre un task pianificato ne è indipendente). Richiede `windows/cred.bat` (vedi `cred.bat.example`, non versionato) con le stesse credenziali Telegram del Mac.
- `minipc/telegram_relay.py` — script che gira **sempre acceso** su un secondo PC (nel nostro caso un mini PC Linux), in ascolto sui comandi Telegram `/avvia`, `/stato`, `/stop` (anche come pulsanti/tastiera, non solo testo). Su `/avvia` manda un pacchetto Wake-on-LAN al PC Windows, aspetta il boot, poi via SSH lancia il task pianificato. Nessuna dipendenza esterna (solo libreria standard Python). Gira come servizio `systemd --user` (vedi `minipc/telegram-relay.service`) con `loginctl enable-linger` abilitato, così resta attivo anche senza sessione utente loggata. Richiede `minipc/cred_relay` (vedi `cred_relay.example`, non versionato).
- `minipc/bot_control.py` — logica condivisa (Wake-on-LAN, SSH, lettura stato) usata sia dal relay Telegram che dalla dashboard web, per non duplicarla.
- `minipc/dashboard.py` + `minipc/static/index.html` — dashboard web (pulsanti Avvia/Stop, statistiche in tempo reale, log live del bot), servita dal mini PC su `http://<ip-minipc>:8090`, pensata per essere raggiunta solo dalla rete di casa. Gira come servizio `systemd --user` (`minipc/dashboard.service`). Legge il contatore attacchi e l'ultima soglia elisir letta da `status.json`, scritto dal bot stesso (vedi `STATUS_FILE` in `BOT_COMPLETO_MAC.py`).

Requisiti lato PC Windows perché tutta la catena funzioni da spento:
- Wake-on-LAN abilitato sia nel driver di rete (`Get-NetAdapterPowerManagement`) sia col comando `powercfg`, e **Fast Startup disattivato** (`HiberbootEnabled=0` — altrimenti dopo uno spegnimento completo il WoL non funziona, solo dopo la sospensione)
- **Auto-login** configurato (via [Sysinternals Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon)): senza una sessione interattiva attiva dopo il boot, né il task né BlueStacks (app grafica) possono partire
- OpenSSH Server installato e abilitato, con la rete impostata su profilo **Privato** (non Pubblico, altrimenti la regola firewall di OpenSSH non si applica)
- Se l'account Windows è collegato a un account Microsoft, va convertito in account locale (Impostazioni → Account → "Accedi con un account locale") — altrimenti né l'auto-login né il cambio password locale funzionano

⚠️ Se usi questo PC anche per esami universitari con software di proctoring: disinstalla BlueStacks e disattiva SSH/RDP prima di ogni esame — i proctoring tool spesso rilevano sia virtualizzatori che strumenti di accesso remoto attivi.

## File generati (non versionati)

Questi file/cartelle vengono creati durante l'uso e sono esclusi da git (vedi `.gitignore`), perché sono output/dati personali, non codice:

- `cred` — le tue credenziali Telegram
- `debug.png` — ultimo screenshot post-elaborazione letto dall'OCR del bottino
- `calibrate.png` — screenshot di riferimento generato da `--calibrate`
- `venv/` — il virtualenv Python
- `__pycache__/` — cache di Python
- `windows/cred.bat`, `minipc/cred_relay` — credenziali Telegram per gli script di controllo remoto
