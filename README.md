# OCR Bot

Bot in Python per macOS che automatizza il farming in un gioco da browser/desktop: legge un valore numerico da una zona fissa dello schermo tramite OCR (Tesseract), e in base alla soglia raggiunta esegue sequenze di click predefinite. Invia inoltre notifiche su Telegram all'inizio, alla fine e in caso di interruzione della sessione.

⚠️ **Attenzione**: automatizzare i click in un gioco può violare i termini di servizio del gioco stesso e portare al ban dell'account. Usalo a tuo rischio e solo se sei consapevole delle conseguenze.

## Come funziona

1. Ogni `POLL_INTERVAL` secondi cattura uno screenshot della zona `OCR_REGION` e ci legge un numero con Tesseract (preprocessing con OpenCV: grayscale, resize, blur, threshold Otsu).
2. Se il valore letto supera `THRESHOLD`, esegue una sequenza di click (scroll + selezione unità + abilità), fino a un massimo di `MAX_TRIGGERS` volte, poi si ferma da solo.
3. Se il valore è sotto soglia, clicca un punto specifico invece di eseguire la sequenza completa.
4. Se per `NO_NUMBER_TIMEOUT` secondi non riesce a leggere nessun numero (es. schermata diversa dal previsto), clicca un punto di recovery.
5. Dopo `SESSION_DURATION` (default 50 minuti) si ferma automaticamente.
6. Ad ogni evento importante (fine sessione, timeout, interruzione manuale) invia un messaggio Telegram.

`debug.png` viene sovrascritto ad ogni lettura OCR con l'immagine post-elaborazione: utile per capire se Tesseract sta leggendo bene la zona giusta.

## Struttura del progetto

```
ocr-bot/
├── BOT_COMPLETO_MAC.py   # script principale
├── requirements.txt      # dipendenze Python
├── cred                  # credenziali Telegram (NON versionato, va creato da te)
├── debug.png              # screenshot di debug (rigenerato ad ogni lettura, NON versionato)
└── venv/                  # virtualenv Python (NON versionato)
```

## Requisiti

- macOS (lo script rileva anche Windows/Linux, ma le coordinate dei click sono calibrate su un Mac 1440x900)
- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installato:
  ```bash
  brew install tesseract
  ```
- Un bot Telegram (per le notifiche): crealo con [@BotFather](https://t.me/BotFather) per ottenere il token, e recupera il tuo `chat_id` (es. scrivendo al bot e leggendo `https://api.telegram.org/bot<TOKEN>/getUpdates`)
- **Permessi macOS**: la prima volta che lo lanci, macOS chiederà di autorizzare il Terminale (o l'app da cui lo lanci) per **Accessibilità** e **Registrazione schermo**, necessari a `pyautogui` (click automatici) e `mss` (screenshot). Vai in *Impostazioni di Sistema → Privacy e Sicurezza* per concederli se non compare il popup.

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

# 3. carica le credenziali e avvia il bot
source cred
python BOT_COMPLETO_MAC.py
```

## Calibrazione delle coordinate

Le coordinate di `OCR_REGION` e delle varie sequenze di click nello script sono calibrate su una risoluzione specifica (Mac 1440x900). Se la tua risoluzione/scaling è diversa, vanno ricalibrate.

Lo script include una modalità di calibrazione che stampa in tempo reale la posizione del mouse:

```bash
python BOT_COMPLETO_MAC.py --calibrate
```

Muovi il mouse sui punti di interesse, leggi le coordinate stampate a schermo, e aggiornale nelle costanti in cima al file (`OCR_REGION`, `CLICK_SEQUENCE`, `SECOND_CLICK_SEQUENCE`, `THIRD_CLICK_SEQUENCE`, `LOW_VALUE_POINT`, `NO_NUMBER_CLICK_POINT`, `DRAG_START`/`DRAG_END`). Premi `Ctrl+C` per uscire.

## Parametri principali

Tutti i parametri configurabili sono in cima al file (`BOT_COMPLETO_MAC.py`):

| Parametro | Significato |
|---|---|
| `OCR_REGION` | Zona dello schermo (in pixel) da cui leggere il numero |
| `THRESHOLD` | Soglia sopra la quale scatta la sequenza completa di click |
| `POLL_INTERVAL` | Ogni quanti secondi leggere il valore OCR |
| `CLICK_INTERVAL` | Pausa tra un click e l'altro nelle sequenze |
| `TRIGGER_COOLDOWN` | Tempo minimo tra due trigger consecutivi sopra soglia |
| `NO_NUMBER_TIMEOUT` | Secondi senza lettura valida prima di eseguire l'azione di recovery |
| `SESSION_DURATION` | Durata massima della sessione (default 50 minuti) |
| `MAX_TRIGGERS` | Numero di trigger sopra soglia dopo cui il bot si ferma da solo |

## File generati (non versionati)

Questi file/cartelle vengono creati durante l'uso e sono esclusi da git (vedi `.gitignore`), perché sono output/dati personali, non codice:

- `cred` — le tue credenziali Telegram
- `debug.png` — ultimo screenshot post-elaborazione letto dall'OCR
- `venv/` — il virtualenv Python
- `__pycache__/` — cache di Python
