# Bot Villaggio Costruttori (secondo villaggio) — stato del lavoro

Bot per il **Villaggio Costruttori** di Clash of Clans. Codice vero in `bot_costruttori.py` (v0.12 al 2026-08-04), standalone rispetto al bot del villaggio primario (`BOT_COMPLETO_MAC.py`): i due non possono girare insieme, perché pilotano la stessa istanza BlueStacks via ADB. Leggi questo file insieme al `README.md` alla radice (architettura remota condivisa: mini PC, PC Windows, ADB, Telegram) e a `recap.md` (cronologia completa, molto più dettagliata, di come si è arrivati qui — in particolare le sessioni del 2026-07-30/31 e del 2026-08-04).

## Stato: automatizzato e collegato a Telegram

- **Flusso di attacco** (doppio raid + schieramento): scritto, testato dal vivo più volte — fino a **200% di danno totale, 3 stelle su entrambi i raid**.
- **Cambio villaggio automatico**: il bot controlla da solo all'avvio se il gioco è rimasto aperto sul villaggio sbagliato (primario invece di Costruttori) e passa da solo toccando la "barca", prima di iniziare. Ricalibrato il 2026-08-04 (v0.10) dopo che un nuovo badge dell'evento stagionale aveva iniziato a coprire il punto di tap originale.
- **Rilevamento fine-raid via OCR**: legge la scritta in alto ("La battaglia inizia/termina tra:") per sapere subito quando il raid corrente è finito e il successivo è pronto, invece di aspettare un tempo fisso.
- **Raccolta elisir dal carretto**: automatizzata, ogni 10 cicli (`COLLECT_ELIXIR_EVERY`, prima era ad ogni ciclo - cambiato il 2026-08-04 su richiesta esplicita dell'utente).
- **Avviabile da Telegram**: bottone "🏗️ Villaggio Secondario" → "▶️ Avvia" (vedi `minipc/telegram_relay.py` + task Windows `CoCBotCostruttori` + `windows/run_bot_costruttori.bat`).
- **Upgrade mura del Villaggio Costruttori**: `try_wall_upgrade()` scritta, **confermata funzionante con spesa reale verificata** e collegata al loop automatico ogni 20 cicli (v0.13, 2026-08-04) — vedi sezione dedicata sotto.

**Le coordinate esatte, le soglie OCR e la cronologia di calibrazione/debug sono nel codice stesso** (`bot_costruttori.py`, commenti estesi su ogni costante) e in `recap.md` — questo file dà solo il quadro d'insieme, per evitare di dover tenere sincronizzati due posti diversi con gli stessi numeri ogni volta che una coordinata viene ricalibrata (successo più volte nella sessione del 2026-07-30/31: swipe camera, coordinate del carretto, ecc.).

## Come funziona questo evento/villaggio

A differenza del villaggio principale:
- **Nessuno scouting**: appena premi "Cerca!" trovi subito un avversario, nessuna schermata di bottino da valutare prima.
- **Doppio attacco**: ogni "giro" sono in realtà **due raid consecutivi**. Il secondo si sblocca solo dopo aver distrutto il primo al 100% — **non è garantito**: se il primo raid non arriva al 100%, il gioco torna dritto alla schermata di ricompensa senza secondo raid (niente di rotto, solo una run da un raid solo). Se il primo va a buon fine, il gioco passa da solo al secondo in 2-3 secondi (non aspetta nessun timer).
- Il secondo raid a volte offre **truppe bonus aggiuntive** oltre a quelle sopravvissute dal primo (slot 7 e 8 nella barra unità).

## Eseguirlo

Da Telegram (consigliato): menu → "🏗️ Villaggio Secondario" → "▶️ Avvia"/"⛔ Stop"/"📊 Stato".

Da riga di comando sul PC Windows (per test manuali, richiede `cred.bat` caricato):
```
python bot_costruttori.py --cycles 1    # un solo ciclo (doppio raid), per un test supervisionato
python bot_costruttori.py --cycles 0    # loop continuo, finché non lo fermi
```

## Upgrade mura (automatizzato, non ancora nel loop)

**Corretta un'ipotesi sbagliata delle sessioni precedenti**: NON è un tap diretto sul segmento di muro con un pannellino a 4-5 pulsanti isolato. È **la stessa tendina/badge "Miglioramenti" del villaggio primario** (tap su `(1115,65)` nella vista di default del Villaggio Costruttori), che si scorre (swipe `(1140,700)->(1140,300)`) cercando voci `Muro`. Su un account rush possono comparire **più voci "Muro" contemporaneamente** a costi diversi (livelli disomogenei) - es. visto dal vivo: "Muro" (8.500 oro), "Muro x130" (127.500 oro), "Muro x41" (204.000 oro) tutte insieme nella stessa tendina.

Selezionando una voce si seleziona **un solo muro fisico specifico**, con un pannello a 4-5 pulsanti: `Info` / (`Selez. Riga`, se compare) / `Migliora ancora` / `Migliora` (oro) / `Migliora` (**"Anello da mura"**, icona ad anello dorato, costo "1" - nome scoperto per caso nella schermata del Pass Stagionale, mai usato in automatico: oggetto raro, mai richiesto dall'utente).

**"Migliora ancora" è il batch, stesso identico meccanismo del villaggio primario**: apre `Togli mura -1` / `Aggiungi mura +10` / `Aggiungi mura +1` / `Migliora` (oro) / `Migliora` (anello) - si aggiungono mura una alla volta con "+1" (mai "+10") controllando il **colore** del costo sul pulsante oro (rosso = fondi insufficienti o mura disponibili esaurite a quel livello), esattamente come `_run_wall_upgrade_round()` nel villaggio primario. Automatizzato in `try_wall_upgrade()`.

**Esiste anche "Selez. Riga"** (seleziona un'intera fila di mura adiacenti, costo totale unico per upgradarle tutte insieme) - esplorato ma **non usato**, su richiesta esplicita dell'utente: si preferisce lo stesso meccanismo +1 del villaggio primario.

**Dialog di conferma finale — diverso da quello del muro singolo, attenzione se si tocca a mano**: dopo "Migliora" (batch) compare "Migliora le mura" / "Vuoi davvero migliorare le mura selezionate per N Oro del costruttore?" con `Annulla`/`OK` — **non** il dialog "Portare al livello N?" con un solo bottone verde che si vede selezionando un muro singolo fuori dal flusso batch. Bug reale trovato il 2026-08-04: usare per errore il punto di conferma del dialog sbagliato fa fallire il pagamento **in silenzio** (nessuna eccezione, nessun errore visibile) - il codice ora verifica esplicitamente che il dialog si sia chiuso (colore di un pixel al centro del box) prima di dichiarare successo.

**Confermato funzionante con soldi veri (2026-08-04)**: 6 mura portate da livello 5 a 6, costo 1.224.000 oro, addebito esatto verificato sul saldo prima/dopo. Un tentativo successivo con oro insufficiente ha correttamente rifiutato di spendere (nessun falso positivo).

**Collegato al loop automatico dal 2026-08-04** (v0.13): scatta da solo ogni 20 cicli (`WALL_UPGRADE_EVERY`, su richiesta esplicita dell'utente), subito dopo un ciclo di attacco riuscito. Un eventuale errore qui non conta come ciclo fallito (l'attacco è comunque andato a buon fine) - loggato e notificato via Telegram a parte, senza contribuire al contatore `consecutive_errors` che fermerebbe la sessione.

## Perché la camera fa solo un pan fisso, non un vero zoom

Tentativi falliti di replicare lo zoom-out che l'utente usa a mano (tasto "freccia giù" tenuto premuto in BlueStacks):
- **Tasto via ADB** (`input keyevent`): nessun effetto — il gioco non ascolta il tasto direttamente, lo zoom è una mappatura di BlueStacks a livello Windows.
- **Tasto sintetico Windows** (`keybd_event` via PowerShell su SSH): nessun effetto — un processo lanciato via SSH gira in una "window station" isolata, non può inviare input alla sessione desktop reale.
- **Pizzico a due dita raw** via `sendevent` sul device touchscreen virtuale: la camera si è mossa ma **non ha zoomato** — solo un pan.

**Soluzione adottata**: uno swipe fisso (non un vero zoom) porta la camera in una posizione ripetibile prima di ogni schieramento. La distanza esatta dello swipe è stata ricalibrata più volte dal vivo (vedi commenti su `CAMERA_SWIPE_START`/`END` nel codice e `recap.md` per la cronologia) — se su una base nuova lo schieramento fallisce sistematicamente, il metodo della griglia (screenshot + overlay a celle, chiedere all'utente dove cade il bordo valido) resta l'opzione più affidabile per ricalibrare, invece di aggiustamenti alla cieca.

## File in questa cartella

- `bot_costruttori.py` — il bot vero, standalone (vedi in cima al file i commenti VERSION/ATTENZIONE per lo stato più aggiornato e le parti ancora da consolidare).
- `prototipo_vecchio_pyautogui.py` — vecchio prototipo pre-ADB, riferimento storico, non riusabile (coordinate su risoluzione diversa, `pyautogui` invece di ADB, nessun controllo di stato/OCR/retry).
