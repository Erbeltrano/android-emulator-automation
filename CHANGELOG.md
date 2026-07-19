# Changelog

Ogni voce spiega cosa è cambiato e **perché**, non solo il cosa — per quello basta `git log`. Il numero di versione è quello in `VERSION` in cima a `BOT_COMPLETO_MAC.py`.

## v1.7 — Nuovo esercito (drago elettrico + macchina d'assedio), fix zona di schieramento, randomizzazione leggera
- Aggiornato l'esercito a 10 draghi elettrici + 1 macchina d'assedio (mongolfiera d'assedio): ogni slot truppa ora ha il proprio numero di tap (10 per il drago, 1 per la macchina d'assedio) invece di un unico conteggio condiviso pensato per truppe con lo stesso numero di unità.
- La zona di schieramento è stata spostata più lontana dal bordo base (+80 orizzontale, +60 verticale) perché capitava che alcuni punti cadessero nella "zona rossa" (non valida) su basi con mura/edifici più estesi di quella su cui era stata calibrata la zona originale, schierando solo parte delle truppe. Aggiustamento fatto senza rilettura dal vivo del colore verde/rosso, da verificare/ritarare se continua a capitare.
- Randomizzazione leggera dei tap di schieramento: piccolo scarto di posizione casuale (non più lo stesso pixel esatto ogni volta), ordine dei punti mescolato, tempi tra un tap e l'altro variabili invece che fissi.
- **Perché:** timore giustificato di ban con un pattern di gioco troppo identico/prevedibile a ogni attacco; la zona di schieramento fissa (voluta esplicitamente per coerenza) andava comunque adattata perché troppo vicina al bordo di alcune basi.
- **Nota:** questa è una randomizzazione volutamente leggera. Una randomizzazione più spinta (pause di esitazione, sessioni più irregolari) è pianificata per la v1.8.
- Posizioni della barra truppe/eroi (`TROOP_SLOTS`, `HERO_SLOTS`) ricalibrate dal vivo su uno screenshot ADB reale con il nuovo esercito, non più assunte.
- **Bug trovato in un test dal vivo:** se ADB/BlueStacks va giù a metà sessione (es. l'emulatore crasha), ogni attacco falliva subito con un'eccezione e il ciclo riprovava ogni 5 secondi fino a fine sessione, mandando un messaggio Telegram di errore ad ogni tentativo (decine in pochi minuti). Ora dopo 3 errori consecutivi il bot si ferma con un solo avviso invece di continuare a martellare alla cieca.

## v1.6 — Attacchi basati sulla risorsa scarsa in casa + storico sessioni
- Prima di iniziare a farmare, il bot ora legge oro/elisir/dark elisir in casa e capisce quale risorsa scarseggia di più (rispetto a soglie "scarso" configurabili dalla dashboard); per tutta la sessione attacca solo bersagli ricchi di *quella* risorsa, invece di guardare solo l'elisir come prima. Oro/elisir/dark elisir hanno ora anche soglie di attacco separate, non un'unica soglia elisir.
- La dashboard ha una nuova sezione **Storico sessioni**: riepilogo (data, durata, attacchi, risorsa prioritaria, bottino stimato) delle ultime sessioni, salvato in `history.json` sul PC Windows a fine sessione.
- **Perché:** con Ranked/Casual i trofei non sono più un problema, ma continuare a inseguire solo l'elisir non ha senso quando in realtà in quel momento serve oro o dark elisir per gli upgrade in corso; lo storico serve a vedere l'andamento nel tempo senza doverlo tenere a mente sessione per sessione.
- **Nota:** il bottino nello storico è una stima (il bottino "disponibile" visto in fase di scouting sui bersagli attaccati), non il bottino realmente incassato a fine battaglia, che il gioco non espone via OCR semplice.
- Le 5 nuove regioni OCR (oro/dark elisir in scouting e in casa) sono state calibrate e verificate dal vivo su BlueStacks. Durante la calibrazione è emerso che Tesseract in modalità "singola riga" (psm 7) falliva silenziosamente sui numeri con separatore delle migliaia quando il testo copre più del ~30% della regione (es. "26 000 000" in casa): passato a psm 13 ("raw line"), che legge correttamente sia i numeri lunghi che quelli corti.
- La lettura delle risorse in casa ora aspetta che il villaggio sia davvero stabile a schermo (`is_home_screen()`) prima di leggere, con un ritentativo se la prima lettura risulta completamente vuota — nei test dal vivo capitava che, appena il gioco si apriva, la lettura cadesse durante un'animazione/popup del primo accesso del giorno.

## v1.5.1 — Corregge un blocco a fine sessione
- A fine sessione (naturale o per `MAX_TRIGGERS`), un `print` con un'emoji (es. "✅") su una console Windows con code page limitata mandava un'eccezione non gestita; il codice finiva in un blocco `finally` che aspettava un INVIO da tastiera per chiudere la finestra — INVIO che in un avvio automatico (Task Scheduler/Telegram) non arriva mai, bloccando il processo per sempre.
- **Perché:** scoperto durante un test dal vivo della v1.6 (integrato anche li'). Un bot "appeso" così impedisce anche ai lanci successivi di partire (lo scheduled task ignora un avvio se ne vede già uno "in corso") — probabilmente la causa di eventuali casi passati in cui il bot sembrava "non partire" da Telegram. Corretto forzando l'encoding UTF-8 su stdout/stderr e rendendo l'attesa dell'INVIO opt-in (flag `--pause-on-exit`) invece che automatica per qualunque console.

## v1.5 — Parametri di farming configurabili dalla dashboard
- La dashboard ha ora una sezione **Impostazioni** (soglia elisir minima per attaccare, numero massimo di attacchi, durata sessione) salvata in `config.json` sul PC Windows e letta dal bot ad ogni avvio.
- **Perché:** evitare di dover modificare il codice e ridistribuire lo script ogni volta che si vuole cambiare la strategia di farming (es. abbassare la soglia in orari con meno basi ricche disponibili).

## v1.4 — Dashboard web e recupero da popup imprevisti
- Aggiunta una **dashboard web** (`minipc/dashboard.py` + `minipc/static/index.html`), raggiungibile dalla rete di casa (e da fuori via Tailscale), con pulsanti Avvia/Stop, statistiche in tempo reale e log live del bot.
- La logica di avvio/stato/stop (Wake-on-LAN + SSH verso il PC Windows) è stata estratta in `minipc/bot_control.py`, condivisa sia dal relay Telegram che dalla dashboard, invece di duplicarla.
- Il bot scrive `status.json` (contatore attacchi, ultima soglia elisir letta) per esporre dati reali alla dashboard, senza inventare metriche finte.
- Se un popup imprevisto sopra al villaggio (es. "Miglioramento completato!") assorbe il tap su "Attacco!", la sequenza di tap successivi rischiava di cadere ancora sul villaggio e premere pulsanti sbagliati (es. il Negozio). Ora il bot verifica di essere davvero uscito dal villaggio dopo il tap, riprova una volta, e se non si sblocca salta il ciclo avvisando via Telegram invece di continuare alla cieca.
- **Perché:** Telegram va benissimo per i comandi rapidi, ma per guardare log/statistiche una pagina web è più comoda; il fix dei popup serve perché nei test dal vivo capitava che il bot, bloccato da un popup, finisse per premere pulsanti del villaggio non previsti.

## Controllo remoto via Telegram (mini PC + PC Windows)
- Aggiunto un **relay Telegram** (`minipc/telegram_relay.py`) su un secondo PC sempre acceso (mini PC): comandi `/avvia`, `/stato`, `/stop` (anche come pulsanti nella tastiera del bot Telegram) che svegliano il PC Windows via Wake-on-LAN, aspettano il boot, e lanciano il bot tramite Task Scheduler.
- Il bot è passato a girare principalmente su un **PC Windows** con BlueStacks invece che sul Mac, tenuto spento quando non serve.
- **Perché:** poter far partire il bot da fuori casa (es. mentre si è al lavoro/università) senza dover tenere acceso e impegnato il portatile personale.

## v1.2 — Supporto Windows
- Aggiunti i percorsi candidati di `adb` e `tesseract` per Windows accanto a quelli Mac: lo stesso script gira identico su entrambi, perché la calibrazione delle coordinate si basa sullo screenshot ADB (1920×1080), non sullo schermo host.
- **Perché:** passo propedeutico a poter usare il PC Windows fisso (più potente) invece del Mac.

## v1.1 — Robustezza del ciclo di attacco
- Rilevamento home-screen basato su un pixel di riferimento, per capire in modo affidabile se siamo nel villaggio o in battaglia/ricerca (invece di fidarsi solo dei tempi di attesa).
- Scroll automatico verso la zona di schieramento prima di schierare le truppe.
- Fine battaglia automatica (tap su "Termina battaglia") invece di aspettare il timer naturale di gioco.
- **Perché:** nei primi test dal vivo il bot a volte schierava truppe nella base propria per errore, o restava fermo ad aspettare la fine naturale di una battaglia già decisa, sprecando tempo di sessione.

## Origini
- Il progetto è partito come script che pilotava direttamente lo schermo del Mac (`pyautogui`-style), poi riscritto per pilotare BlueStacks via ADB (screenshot + tap/swipe): questo ha permesso di far girare il bot in background, senza bisogno che la finestra di BlueStacks fosse visibile o a fuoco.
