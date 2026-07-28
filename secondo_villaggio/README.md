# Bot Villaggio Costruttori (secondo villaggio) — stato del lavoro

Bot per il **Villaggio Costruttori** di Clash of Clans, pensato per girare sulla stessa architettura ADB del bot principale (`BOT_COMPLETO_MAC.py`), come modulo separato da integrare in seguito. **Nessun codice Python scritto ancora** — tutto il flusso qui sotto è stato calibrato e validato pilotando l'emulatore a mano via ADB (comandi diretti, non uno script), la sera del 2026-07-27. Leggi questo file insieme al `README.md` alla radice (spiega l'architettura remota condivisa: mini PC, PC Windows, ADB, Telegram) e a `recap.md` (cronologia completa di come si è arrivati qui).

## Stato: flusso di attacco + upgrade mura + raccolta elisir tutti calibrati e funzionanti

Testato dal vivo più volte, su basi avversarie diverse, risultato consistente: **200% di danno totale, 3 stelle su entrambi gli attacchi** del doppio raid.

## Come funziona questo evento/villaggio

A differenza del villaggio principale:
- **Nessuno scouting**: appena premi "Cerca!" trovi subito un avversario, nessuna schermata di bottino da valutare prima.
- **Doppio attacco**: ogni "giro" sono in realtà **due raid consecutivi**. Il secondo si sblocca solo dopo aver distrutto il primo al 100%. Le truppe che sopravvivono al primo attacco **vengono portate al secondo** (barre vita piene/parziali, non si riparte da un esercito fresco) — per questo è importante farle sopravvivere (vedi "attivazione abilità" sotto), non solo fare più danno possibile.
- Il secondo attacco a volte offre **truppe bonus aggiuntive** oltre a quelle sopravvissute dal primo (es. due draghetti visti in test, slot 7 e 8 nella barra).

## Flusso di attacco calibrato

1. **Tap "Attacco!"** `(110, 990)` nella home del villaggio costruttori.
2. **Tap "Cerca!"** `(1425, 710)` nel popup "Inizia attacco".
3. **Aspettare esattamente ~3 secondi, poi agire subito — non aspettare la fine del countdown pre-battaglia.** Il countdown dura circa 40s ma se lo si aspetta tutto si rischia di non fare in tempo a schierare prima che scada il tempo della battaglia vera e propria (successo un fallimento con 0% di danno per questo motivo). Nota: a volte può comparire un pannello imprevisto "Cambia truppe" (causa non chiara — forse un tap finito fuori bersaglio durante il countdown) che si chiude da solo ma fa perdere tempo prezioso: altro motivo per muoversi in fretta appena possibile invece di aspettare.
4. **Swipe fisso per portare la camera in una posizione ripetibile**: `input swipe 960 600 960 300 600`. Non è un vero zoom (vedi sezione "Perché non zoomiamo" sotto) ma un pan fisso — **confermato che genera un'inquadratura coerente su basi avversarie diverse** (testato su 3 basi distinte).
5. **Schierare ogni unità**: per ciascuna (eroe compreso, poi le truppe nella barra in basso da sinistra a destra, poi eventuali slot bonus tipo draghi):
   - tap sull'icona della truppa nella barra in basso (es. eroe `(195,990)`, truppe successive a passi di ~160px: `355, 515, 675, 835, 995, 1155, 1315, 1475`, tutte a `y=990`)
   - tap su uno dei due punti di sgancio fissi calibrati: **H4 = `(1200,720)`** oppure **I3 = `(1360,560)`** (vedi "Metodo della griglia" sotto per come sono stati trovati — vanno bene alternati, non serve un punto diverso per ogni truppa)
   - pausa ~200-400ms tra un tap e l'altro
6. **Dopo ~2 secondi dalla fine dello schieramento, ri-toccare ogni icona truppa nella barra in basso** (stesso punto del tap di schieramento) per attivarne le abilità — passaggio indicato dall'utente, indispensabile per far sopravvivere le truppe abbastanza da portarle al secondo attacco.
7. Alla fine del **secondo** attacco, ripetere lo swipe fisso (punto 4) + schieramento (punti 5-6) — stessa identica logica, includendo eventuali truppe bonus del secondo round.
8. Schermata di vittoria → **tap "Torna al villaggio"** `(960, 910)`.
9. A volte compare un popup extra **"Bonus stella!"** → tap OK `(960, 838)` per chiuderlo.

## Metodo della griglia (per ricalibrare i punti di sgancio, se serve)

Se in futuro serve ritrovare/aggiustare le coordinate di schieramento: si prende uno screenshot della schermata di battaglia (dopo lo swipe fisso), ci si disegna sopra una griglia di riferimento (celle 160×160px, etichettate lettera=colonna + numero=riga, es. `H4`), la si mostra e si chiede a voce in che cella piazzare le truppe. Molto più affidabile che indovinare pixel a occhio. Script Python usato (PIL, `ImageDraw`) non salvato come utility separata — era inline nella conversazione, da ricreare al bisogno (poche righe: disegna linee ogni 160px + etichetta ogni cella).

## Upgrade mura

Diverso dal villaggio principale: **niente menu/dropdown del badge costruttore**. Si tocca **direttamente il segmento di muro sulla mappa di casa** (qualsiasi punto del muro) e si apre subito un pannellino con 5 pulsanti: `Info` / `Selez. Riga` / `Migliora ancora` / `Migliora` (oro, importo mostrato in chiaro) / `Migliora` (un'altra valuta, icona ad anello/guanto dorato, costo mostrato come "1").

**La seconda valuta non è stata identificata** (non è elisir — l'elisir ha sempre l'icona a goccia viola, questa no) — potrebbe essere gemme o un materiale specifico dell'evento. **Deciso di non toccarla finché non è chiara**: si usa solo il pulsante oro esplicito.

Flusso di conferma:
1. Tap sul pulsante "Migliora" (oro).
2. Si apre un dialog "Portare al livello N?" con un pulsante verde di conferma (mostra di nuovo il costo in oro).
3. Tap sul pulsante verde per confermare — spende davvero.

**Testato dal vivo con soldi veri**: muro portato da livello 4 a livello 5, costo 120.000 oro, addebito esatto (verificato confrontando il saldo prima/dopo), elisir non toccato.

**Se il pannello resta aperto per sbaglio** (es. un tap finito su un muro per errore, capitato due volte durante i test): si chiude in sicurezza toccando una zona vuota della mappa (es. `(950, 120)`, area cielo/vuoto in alto). Nessun rischio di spesa accidentale: serve comunque un tap esplicito su "Migliora" **più** la conferma nel dialog per spendere qualcosa — il solo aprire il pannello non costa nulla.

## Raccolta elisir dal carretto

**Trovato e testato dal vivo con soldi veri.** Il "carretto" non è un contenitore del bottino dei propri attacchi (equivoco iniziale) ma raccoglie le **ricompense dalle difese**: ogni volta che lanci un assalto, in cambio il gioco fa difendere la tua base da un avversario, e la ricompensa di quella difesa si accumula nel carretto (cap `1.600.000` elisir) finché non lo svuoti — se non lo svuoti in tempo, quelle ricompense andrebbero sprecate (stesso concetto di `storage_is_full()` nel bot principale, ma qui è un oggetto fisico sulla mappa da individuare e toccare, non una percentuale letta dalla barra risorse).

Flusso:
1. Dalla home di default, **swipe verso l'alto per pannare la camera**: `input swipe 960 300 960 700 600` (stesso comando usato per esplorare la mappa, non lo swipe fisso pre-battaglia che va nella direzione opposta).
2. Il carretto (icona: fiala viola con base di legno e ruote, marcatore a goccia viola sopra) compare **sulla destra dello schermo**, circa `(1275, 460)`.
3. Tap sul carretto → si apre il popup **"Carretto di elisir"**: lista delle ultime difese (nome attaccante, % danno, stelle, elisir guadagnato) più una barra riepilogo in basso "Ricompense dalle difese: N / 1.600.000" con pulsante **"Prendi"** `(1410, 910)`.
4. Tap su "Prendi" → incassa tutto l'elisir accumulato nel deposito principale (**confermato**: +576.000 elisir esatti in un test, saldo verificato prima/dopo). Il popup resta aperto e la barra si azzera (mostra "Non ci sono nuove ricompense dalle difese" se non c'è altro da prendere).
5. Chiudi con la X in alto a destra del popup, `(1620, 105)`.

Se non ci sono nuove ricompense, il tap su "Prendi" è comunque sicuro (nessun effetto collaterale, il pulsante resta lì disabilitato/inutile ma non genera errori).

## Cosa manca — prossimi passi

### Perché non zoomiamo (invece di fare pan fisso)

Tentativi falliti di replicare lo zoom-out che l'utente usa a mano (tasto "freccia giù" tenuto premuto in BlueStacks):
- **Tasto via ADB** (`input keyevent`, anche `--longpress`): nessun effetto — il gioco non ascolta il tasto direttamente, lo zoom è una mappatura di BlueStacks a livello Windows.
- **Tasto sintetico Windows** (`keybd_event` via PowerShell su SSH): nessun effetto — un processo lanciato via SSH gira in una "window station" isolata, non può inviare input alla sessione desktop reale. Confermato anche a basso livello: perfino `OpenInputDesktop` (API Win32 per agganciarsi alla sessione interattiva) fallisce con errore di sistema da un contesto SSH.
- **Pizzico a due dita raw** via `sendevent` sul device touchscreen virtuale (`/dev/input/event4`, multitouch reale Protocol B): eseguito con successo (script push su `/data/local/tmp/` + `adb shell sh`), la camera si è mossa ma **non ha zoomato** — solo un pan, secondo l'osservazione diretta dell'utente.

**Soluzione adottata**: uno swipe fisso singolo (non un vero zoom) porta la camera in una posizione ripetibile prima di ogni schieramento — sufficiente per avere coordinate di sgancio affidabili, senza bisogno di risolvere lo zoom vero.

### Confronto con il vecchio prototipo (`prototipo_vecchio_pyautogui.py`)

Quel file resta come riferimento storico ma **non è riusabile direttamente**: coordinate calibrate su una risoluzione diversa da 1920×1080 (i valori superano 1080 in verticale), nessun controllo di stato/OCR/retry, `pyautogui` invece di ADB.

- ✅ **Avvio attacco** (sua `SEQUENZA 1`/`SEQUENZA 5`) e **schieramento truppe** (sua `SEQUENZA 4`) — rifatti da zero con il metodo della griglia, meglio dell'originale (calibrati a vista, verificati su basi diverse).
- ✅ **Fine battaglia / ritorno al villaggio** (sua `SEQUENZA 2`) — rifatto, testato.
- ✅ **Svuotamento carretto elisir** (sua `SEQUENZA RACCOLTA` + `SEQUENZA 3` finale) — **non riusato**, esplorato da zero con successo (le sue coordinate erano comunque su risoluzione sbagliata e la logica non era mai stata chiarita nemmeno a suo tempo). Vedi sezione dedicata sopra.

### Poi

Fatti girare più cicli di fila per validare la stabilità del flusso completo (attacco + raccolta + mura): scrivere il codice vero come modulo Python sull'architettura del bot principale (ADB con retry — vedi `_adb_retry()` in `BOT_COMPLETO_MAC.py` — invece di comandi sciolti), poi decidere con l'utente come integrarlo nel loop principale (processo unico che alterna i due villaggi, discusso ma non deciso — vedi `recap.md`).

## Nota sul doppio attacco: non è garantito

Testato con 5 cicli di fila (stessa sera): il secondo attacco si sblocca **solo** se il primo raggiunge il 100%/3 stelle. Con lo schema di deploy H4/I3 attuale, su alcune basi le truppe non bastano per il 100% (visto: 80% e 75% in due cicli su 2) — in quel caso il gioco torna dritto alla schermata di ricompensa **senza secondo attacco**, niente di rotto, solo una run da un solo raid invece di due. Da tenere conto quando si scrive il codice vero: la logica "porta le truppe sopravvissute al secondo attacco" è condizionale, non sempre applicabile.

## File in questa cartella

- `prototipo_vecchio_pyautogui.py` — vecchio prototipo, riferimento storico, non riusabile (vedi sopra).
- Nessuno screenshot tenuto: quelli accumulati durante la calibrazione del 2026-07-27 sono stati cancellati (erano solo debug visivo, tutto il necessario è già scritto in forma testuale sopra) per alleggerire il progetto.
