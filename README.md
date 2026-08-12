# OCR Bot — Clash of Clans (headless via ADB)

**Versione:** 3.15 (vedi `VERSION` in cima a `BOT_COMPLETO_MAC.py`)

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
4. Aspetta che la battaglia finisca leggendo via OCR la percentuale di "Danno complessivo" ogni `DAMAGE_POLL_INTERVAL` secondi (`wait_for_battle_end()`, v3.1): se resta ferma per `DAMAGE_STALL_SECONDS` (truppe morte/esaurite, nessun altro danno in arrivo) termina subito invece di aspettare un tempo fisso a schermo fermo. `BATTLE_DURATION_WAIT[1]` resta come tetto massimo di sicurezza se l'OCR del danno smette di funzionare. Poi torna al villaggio.
5. Ripete finché i depositi di oro ed elisir in casa non sono quasi pieni (letto dal vivo tramite il tooltip "Max" della barra risorse, non un valore fisso), poi si ferma da solo. `MAX_TRIGGERS` attacchi / `SESSION_DURATION` (default 50 minuti) restano come tetto di sicurezza se la lettura della capacità dei depositi dovesse fallire.
6. Se il flag `auto_wall_upgrade` è attivo (dashboard o `/muraon` su Telegram) e c'è un costruttore libero, a fine sessione mette in coda l'upgrade di quante più mura possibile con le risorse rimaste in casa (pagando con la valuta più abbondante, un muro alla volta). Se il flusso non riesce a completare nessun upgrade (es. un rilevamento UI fallito), manda un avviso Telegram invece di fermarsi in silenzio con i depositi ancora pieni.
7. I comandi ADB di base (tap, swipe, screenshot) ritentano automaticamente in caso di intoppo transitorio (tipico subito dopo un risveglio a freddo via Wake-on-LAN): un singolo hiccup non conta più come un errore verso il limite di 3 errori consecutivi che ferma la sessione.
8. Dopo aver accettato un avversario, aspetta `BATTLE_START_MAX_WAIT` (4s dalla v3.0 — vedi sotto) prima di schierare. Fino alla v2.8 era pensato per coprire l'intero countdown di matchmaking (fino a ~40s): scoperto poi che non serve, il gioco accetta comunque i tap di deploy durante il countdown (vedi v3.0 sotto).
9. Le pause della UI (scroll, selezione truppe/eroi, tap di schieramento e attivazione abilità) sono state ridotte in modo conservativo in v2.8. Non viene ridotto il countdown di battaglia, che è necessario affinché il gioco accetti il deploy.

### Stato noto del piazzamento

**v2.9**: `DEPLOY_POINTS` ricalibrato da zero col "metodo della griglia" (già usato per `secondo_villaggio`): screenshot di una battaglia reale con overlay a celle 160px, l'utente ha indicato a mano la diagonale del bordo esterno valido di quella base (da cella K1 a G5). I 18 punti attuali sono equispaziati lungo quella diagonale e sostituiscono per intero il vecchio pool sparso (due diagonali diverse assemblate alla cieca in sessioni precedenti, che davano danni bassi con messaggi "Non puoi schierare truppe nella zona rossa"). Da verificare su più basi diverse: se emerge che questa singola diagonale non generalizza, ripetere il metodo della griglia su quella base piuttosto che tornare ad aggiungere punti a caso.

**v3.0**: `BATTLE_START_MAX_WAIT` riportato da `40.0` a `4.0` su richiesta esplicita dell'utente — secondo la sua osservazione dal vivo il piazzamento funziona comunque durante il countdown di matchmaking, quindi il valore alto non sarebbe la spiegazione corretta del bug del 2026-07-28. Da monitorare: se ricompaiono pochi tap a segno/0% danno, il sospetto principale resta questo valore.

**v3.1**: fine battaglia adattiva invece di un'attesa fissa. L'utente ha notato dal vivo che spesso le truppe muoiono quasi subito e il bot restava a "fissare il vuoto" per un minuto o più prima di terminare. `wait_for_battle_end()` ora legge la percentuale di "Danno complessivo" (nuova `OCR_REGION_DAMAGE`, basso a destra) ogni 5s: se non sale per `DAMAGE_STALL_SECONDS` termina subito, se arriva al 100% anche. Nota tecnica sull'OCR: con la whitelist solo-cifre già usata per le risorse, Tesseract forzava il simbolo "%" a diventare la cifra più simile (es. "36%" letto come "365") invece di ignorarlo — risolto includendo "%" nella whitelist e usando `psm 7` (unica modalità testata affidabile sia su numeri a una cifra "2%" che a due "36%" su questo font), poi scartando il simbolo dal risultato.

**v3.2**: `DAMAGE_STALL_SECONDS` alzato da `15.0` a `20.0` — l'utente ha visto dal vivo la battaglia terminare in anticipo con truppe ancora vive: la % di danno può restare ferma diversi secondi per pause normali di combattimento (un'unità che rosicchia un muro, un eroe che cammina tra un edificio e l'altro), non solo perché le truppe sono morte. Se il falso positivo si ripresenta, il valore da alzare ulteriormente è questo.

**v3.3**: `DAMAGE_POLL_INTERVAL` abbassato da `5.0` a `2.0` — con un controllo ogni 5s l'ultimo aumento di danno rilevato poteva essere fino a 5s più vecchio di quando succedeva davvero (si controlla solo a intervalli, non in continuo), facendo scattare lo stallo prima di quanto sembrasse guardando lo schermo. Un controllo più frequente riduce questo ritardo nascosto.

**v3.4**: `DAMAGE_STALL_SECONDS` alzato ulteriormente da `20.0` a `25.0` su richiesta dell'utente.

**v3.5**: bug fix in `wait_for_battle_end()` — due letture OCR fallite di fila (es. l'effetto grafico del fulmine dei draghi elettrici copre il numero del danno per un paio di secondi) facevano terminare subito la battaglia, scambiando l'effetto visivo temporaneo per prova che fosse già finita. Ora una lettura fallita conta solo come "nessun nuovo danno visto in questo istante": il cronometro dei 25s si basa esclusivamente sull'ultima lettura riuscita, non su quante letture falliscono di fila.

**v3.6**: fix per un bug reale — Clash of Clans resta sull'ultimo villaggio visitato tra un avvio e l'altro (primario o Villaggio Costruttori, vedi `secondo_villaggio/`). Se il gioco viene lanciato mentre è rimasto aperto sul villaggio sbagliato, il bot ora se ne accorge (`detect_village_type()`, colore medio di una striscia in alto: verde nel primario, blu/teal nel Villaggio Costruttori) e cambia villaggio da solo toccando la "barca" (`switch_to_village()`), prima di iniziare a leggere/attaccare. Controllo fatto a inizio `main()`, subito dopo aver verificato di essere su una schermata home.

**v3.7**: bug reale trovato dall'utente — con oro/elisir normale quasi sempre pieni ed elisir nero scarso, il bot si fermava comunque appena oro o elisir toccavano il 92% ("depositi quasi pieni, vado a fare le mura"), ignorando del tutto l'elisir nero. Con `auto_wall_upgrade` disattivato ("mura off") il bot restava fermo senza fare nulla, senza mai lasciare tempo all'elisir nero di accumularsi. `storage_is_full()` ora richiede anche che l'elisir nero in casa sia sopra `home_low_dark_elixir` (default alzato da `1500` a `400000`, campo già configurabile da dashboard) prima di considerare i depositi "pieni": se l'elisir nero è sotto soglia, il bot continua a farmare anche con oro/elisir già colmi, fino al tetto di sicurezza su attacchi/durata sessione se il farming di elisir nero è lento.

**v3.8-v3.10** (2026-08-04): `switch_to_village()` (cambio automatico tra villaggio primario e Villaggio Costruttori, v3.6) aveva smesso di funzionare in modo affidabile — tre bug reali trovati e fixati dal vivo via ADB/screenshot: (1) un nuovo badge dell'evento stagionale in corso copriva `BOAT_TO_BUILDER_POINT`, intercettando il tap prima che arrivasse alla barca sottostante; (2) `BOAT_TO_PRIMARY_POINT` non era più valido dopo il pan camera (la barca di ritorno si ferma ora in un punto diverso, probabilmente per lo stesso evento); (3) un bug di logica indipendente dalle coordinate — il controllo di successo avveniva solo *prima* di ogni tap, mai *dopo* l'ultimo, quindi un cambio riuscito al secondo tentativo veniva comunque segnalato come fallito. Tutti e tre confermati risolti con la funzione vera (non solo tap manuali), in entrambe le direzioni, primo tentativo.

**v3.11** (2026-08-07): bug reale trovato dal vivo — con l'elisir nero come risorsa prioritaria e ancora ben sotto soglia (84.000/400.000), il bot si è fermato comunque dopo 7 attacchi ("depositi quasi pieni"). Causa: in `storage_is_full()`, quando la lettura OCR dell'elisir nero fallisce (capita, es. "lettura fantasma" vista nello stesso log pochi cicli prima), la funzione considerava l'elisir nero "pieno" per default — bastava una singola lettura fallita nel momento sbagliato per far scattare uno stop del tutto ingiustificato. Fix: una lettura fallita ora conta come "non pieno" (si continua a farmare), stessa scelta di sicurezza già usata per le letture di oro/elisir max quando falliscono — il tetto di sicurezza su attacchi/durata sessione resta comunque a protezione se l'OCR smette proprio di funzionare.

**v3.12** (2026-08-07, stessa sessione): visto dal vivo un riavvio di BlueStacks resettare lo zoom della camera (vedi sezione "Stato noto del piazzamento" più sotto) e mandare in tilt tutte le letture OCR dello scouting — il vecchio comportamento ("budget di tempo scouting esaurito, attacco comunque l'ultima base trovata") continuava ad attaccare basi alla cieca in loop invece di accorgersi che qualcosa era rotto. Nuovo check in `find_and_evaluate_opponent()`: se in un intero giro di scouting **nessuna** lettura di risorse riesce (zero letture non-None su tutti i tentativi), il ciclo viene saltato invece di attaccare comunque, con un avviso Telegram dedicato che invita a controllare lo schermo — non blocca l'intera sessione (che comunque termina da sola al tetto di durata/attacchi se il problema persiste), ma evita di sprecare attacchi alla cieca ciclo dopo ciclo in silenzio.

**v3.13** (2026-08-09): bug reale trovato dal vivo — elisir ed elisir nero pieni ma oro a 7,9/22 milioni (~32%, "praticamente vuoto" per l'utente), e il bot si è fermato comunque ("depositi quasi pieni"). Causa: `storage_is_full()` si ferma bastando UNA valuta piena tra oro/elisir (scelta esplicita del 2026-07-25, per non sprecare l'altra già colma), ma non proteggeva la valuta NON piena se questa era a sua volta scarsa - stessa classe di bug già fixata per l'elisir nero (v3.7), mai estesa a oro/elisir tra loro. Fix: nuova soglia proporzionale `STORAGE_LOW_RATIO = 0.5` (non i campi assoluti `home_low_gold`/`home_low_elixir` già in config, scartati perché tarati per un deposito piccolo, non per il 50% di un deposito da 22 milioni) - se la valuta non piena è sotto il 50% della propria capacità massima, non ci si ferma anche se l'altra è già piena. Testato dal vivo chiamando `storage_is_full()` sullo stato reale (oro 31%, elisir 100%): confermato ritorna `False`.

**v3.14** (2026-08-10): tre bug reali trovati e fixati dal vivo nella stessa sessione, dopo che l'utente ha segnalato "il bot del secondo villaggio non partiva" e "di nuovo depositi quasi pieni con l'elisir nero vuoto".

1. **Elisir nero: stessa classe di bug della v3.13, mai estesa a lui**. `storage_is_full()` considerava l'elisir nero "pieno" sopra una soglia assoluta fissa (`home_low_dark_elixir`, 400.000) invece che sopra `STORAGE_FULL_THRESHOLD` della vera capacità del deposito, come già fatto per oro/elisir. Verificato dal vivo: capacità vera 430.000, elisir nero in casa 38.995 (9%, genuinamente vuoto) — una soglia assoluta può sembrare quasi corretta per caso oggi, ma smette di funzionare al prossimo potenziamento del deposito. Fix: stessa tecnica di oro/elisir, tooltip "Max" letto dal vivo toccando la barra elisir nero (`DARK_ELIXIR_BAR_POINT`). Durante il fix, trovato anche un bug OCR nel parsing del tooltip ("Max: 430 000" letto con un carattere estraneo in mezzo o una cifra estranea prima di "Max", troncando/gonfiando il numero) — risolto prendendo solo le cifre della riga "Max" a partire dalla parola stessa, non l'intera riga o un pattern rigido.
2. **Villaggio Costruttori "non partiva"**: `switch_to_village("costruttore")` falliva perché la barca si trovava in una posizione leggermente diversa dai punti calibrati in sessioni precedenti (stesso tema ricorrente: lo zoom/pan della camera non è deterministico tra un riavvio e l'altro). Fix: prima di un tap puntuale cieco, si cerca la barca via `cv2.matchTemplate` (immagini di riferimento `boat_to_builder_ref.png`/`boat_to_primary_ref.png`) in una finestra centrata sul punto calibrato — tollera piccoli spostamenti (e in parte anche variazioni di zoom, provando piu' scale) senza dover indovinare altri punti fissi. Se il template match non trova nulla, ricade sul vecchio tap puntuale (nessuna regressione). Applicato a entrambi gli script (`BOT_COMPLETO_MAC.py` e `secondo_villaggio/bot_costruttori.py`), confermato funzionante dal vivo in entrambe le direzioni su entrambi gli script.
3. **La causa vera di "Attacco! non si apre (popup imprevisto?)"**: lasciando il gioco inattivo compare il dialog nativo di Clash of Clans "C'è nessuno? La connessione è stata interrotta per inattività" — un dialog modale che assorbe il tap su "Attacco!" senza coprire il pulsante sottostante, quindi `is_home_screen()` continuava a leggere "siamo in home" e il bot ripeteva lo stesso tap alla cieca all'infinito (osservato dal vivo: 8+ cicli falliti di fila). **Tentato un fix con tap automatico su "RICARICA GIOCO", poi scartato**: testato dal vivo, ha chiuso l'intero processo dell'emulatore invece di ricaricare la partita — rischio peggiore del problema. Fix finale: rilevamento via OCR + foto Telegram automatica di cosa si vede in quel momento (prima l'utente doveva chiederla a parte, causando l'impressione di messaggi contraddittori) + interruzione pulita della sessione (errore vero, contato nel tetto `MAX_CONSECUTIVE_ERRORS`) invece di ritentare all'infinito. Richiede intervento manuale (ricaricare il gioco), nessun tap automatico rischioso.

**v3.15** (2026-08-12): bug reale trovato e fixato in autonomia mentre l'utente era fuori a pranzo, dopo che ha segnalato "il bot del secondo villaggio ha funzionato alla perfezione, quello del primo dava errori". Riprodotto dal vivo (100% deterministico su avvio pulito, stesse identiche coordinate/errore): al primissimo tap/swipe subito dopo l'inizio della battaglia (`scroll_down_by_drag()`, appena finito il countdown di matchmaking — probabilmente durante il caricamento pesante della base avversaria) il bridge ADB di BlueStacks si blocca, e resta bloccato più a lungo di quanto i retry ravvicinati di `_adb_retry` (3 tentativi, 1s di distanza) riescano a coprire — nel log reale ha fatto fallire 3 attacchi consecutivi di fila (swipe + due tap su "Attacco!"), fino allo stop automatico per troppi errori. Fix: nuova `_adb_recover()`, richiamata da `_adb_retry` solo se i retry ravvicinati falliscono tutti — fa ripartire l'adb server (`kill-server` + un `adb devices` innocuo, che da solo basta di norma a farlo ripartire) e ripesca il device (riassegnando `DEVICE` se il serial fosse cambiato), aspettando fino a 20s prima di riprovare il comando originale. Migliorata anche la leggibilità del log degli errori: `[ERRORE]` ora include lo stderr reale del comando adb fallito (prima si vedeva solo "returned non-zero exit status 1", senza il motivo). VERSION → 3.15. Confermato dal vivo: bug riprodotto una prima volta senza il fix (per diagnosticarlo), poi il fix deployato e la sessione live ripartita senza errori.

`debug.png` viene sovrascritto ad ogni lettura OCR del bottino con l'immagine post-elaborazione: utile per capire se Tesseract sta leggendo bene la zona giusta.

Ad ogni evento importante (avvio, fine sessione, errori, interruzione manuale) il bot invia un messaggio Telegram.

## Struttura del progetto

```
ocr-bot/
├── BOT_COMPLETO_MAC.py     # script principale (villaggio primario)
├── builder_badge_zero_ref.png  # riferimento usato da has_free_builder(), deve stare
│                                # nella stessa cartella dello script
├── requirements.txt        # dipendenze Python
├── cred                    # credenziali Telegram (NON versionato, va creato da te)
├── minipc/                 # relay Telegram + dashboard web (girano sul mini PC sempre acceso)
├── windows/                # script di avvio lato PC Windows (run_bot.bat + credenziali)
├── secondo_villaggio/      # lavoro in corso: bot per il Villaggio Costruttori (non ancora integrato,
│                            #   vedi secondo_villaggio/README.md per lo stato dettagliato)
├── archivio/               # roba non più in uso ma tenuta per sicurezza (NON versionato)
└── venv/                   # virtualenv Python (NON versionato)
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

- `windows/run_bot.bat` — script che va sul PC Windows: apre BlueStacks, aspetta che ADB veda il device, avvia Clash of Clans, aspetta 35s che carichi, esegue il dezoom automatico della camera (`windows/dezoom_camera.ps1`, vedi sotto), poi lancia `BOT_COMPLETO_MAC.py`. Lanciato da un **Task Scheduler di Windows** (non da `Start-Process` diretto via SSH: la sessione SSH su Windows lega i processi a un Job Object che li uccide alla disconnessione — e più in generale isola completamente dalla sessione desktop interattiva reale, vedi sotto — mentre un task pianificato con logon interattivo ne è indipendente). Richiede `windows/cred.bat` (vedi `cred.bat.example`, non versionato) con le stesse credenziali Telegram del Mac.
- `windows/dezoom_camera.ps1` — script PowerShell che porta automaticamente la camera di Clash of Clans al livello di zoom minimo, richiamato da `run_bot.bat`/`run_bot_costruttori.bat` subito dopo il caricamento del gioco. **Perché serve**: la posizione/zoom della camera vive solo nello stato live del processo BlueStacks, non è salvata da nessuna parte su disco (verificato il 2026-08-07 tentando senza successo di leggere `shared_prefs` dell'app anche con root abilitato) — si perde ogni volta che BlueStacks riparte da zero (es. il PC Windows spento per inattività e risvegliato via Wake-on-LAN), rendendo `DEPLOY_POINTS`/OCR non più calibrati. **Perché deve girare da un task pianificato e non da SSH diretto**: un comando lanciato via SSH gira in una "window station" isolata dalla sessione desktop interattiva reale — non solo l'input sintetico (`mouse_event`) non la raggiunge mai, ma anche solo *leggere* l'handle della finestra di BlueStacks fallisce (`MainWindowHandle = 0`). Un task pianificato con `LogonType=Interactive` gira invece dentro la sessione vera, dove l'input sintetico funziona davvero (confermato dal vivo il 2026-08-07). Simula lo stesso identico gesto che l'utente fa a mano (tasto destro del mouse tenuto ~2.5s al centro della finestra). **Timing critico**: se lanciato prima che il gioco abbia finito la transizione dalla schermata di caricamento al villaggio, il click viene interpretato come tasto "Indietro" e chiude il gioco invece di zoomare (visto dal vivo: 20s di attesa non bastavano su un riavvio vero da zero) — per questo l'attesa prima di chiamarlo è stata alzata a 35s.
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
