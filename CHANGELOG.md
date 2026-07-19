# Changelog

Ogni voce spiega cosa è cambiato e **perché**, non solo il cosa — per quello basta `git log`. Il numero di versione è quello in `VERSION` in cima a `BOT_COMPLETO_MAC.py`.

## v1.8 — Randomizzazione più spinta, storico più ricco, notifiche migliori, watchdog
- **Randomizzazione più spinta** (pianificata dalla v1.7): ogni sessione ora ha un numero massimo di attacchi e una durata leggermente diversi dal valore configurato (fino a 2 attacchi in meno, fino a 5 minuti in meno), invece di fermarsi sempre esattamente allo stesso punto. Pause di "esitazione" casuali (2-6s prima di un attacco, 1.5-4s prima di schierare) che non capitano ad ogni ciclo. Range di attesa a fine battaglia allargato (45-120s invece di 60-90s).
- **Storico sessioni più ricco**: ora registra anche le sessioni fermate manualmente da dashboard/Telegram (prima solo quelle finite da sole - fine cicli, timeout, troppi errori), con un campo "come è finita" visibile in tabella. Nuovo grafico a barre (attacchi per sessione nel tempo) sopra la tabella nella dashboard.
- **Notifica Telegram di fine sessione più completa**: include ora il bottino stimato totale (oro/elisir/dark elisir), non solo il numero di attacchi.
- **Controllo periodico "il bot è ancora vivo"**: il relay Telegram (che vive sul mini PC sempre acceso) controlla ogni 5 minuti se il PC Windows è ancora raggiungibile mentre una sessione risultava in corso; se sparisce dalla rete senza un messaggio di fine sessione (crash, riavvio inatteso, blackout), avvisa via Telegram invece di lasciare che nessuno se ne accorga.
- **Perché:** il timore di ban con un pattern troppo prevedibile resta valido anche a sessione ormai "collaudata"; lo storico/notifiche più ricchi servono a capire cosa è successo senza dover controllare i log a mano; il watchdog copre lo scenario (successo dal vivo: un blackout notturno) in cui il PC sparisce e nessuno se ne accorge finché non si prova a usare il bot.
- IP del mini PC (MINIPC_IP) fissato via riserva DHCP, come già fatto per il PC Windows: nessuna modifica al codice necessaria.
- **Default della priorità automatica cambiato da elisir a oro**: se nessuna risorsa risulta sotto la sua soglia "scarso" (capita spesso su un account con oro/elisir ben sopra le soglie tipiche, es. 17-22 milioni contro una soglia di 300.000), la sessione ora punta sull'oro invece che sull'elisir. Scelta esplicita dell'utente, non un cambio di logica: le soglie stesse restano quelle configurate.

## v1.7 — Nuovo esercito (drago elettrico + macchina d'assedio), deploy più affidabile, randomizzazione leggera
- Aggiornato l'esercito a 10 draghi elettrici + 1 macchina d'assedio (mongolfiera d'assedio): ogni slot truppa ora ha il proprio numero di tap invece di un unico conteggio condiviso pensato per truppe con lo stesso numero di unità. Posizioni della barra truppe/eroi ricalibrate dal vivo su screenshot ADB reali (presa in scouting E durante la battaglia vera, che hanno lo stesso layout).
- **Deploy molto più affidabile dopo diversi giri di test dal vivo:**
  - I punti di schieramento sono tornati alle coordinate originali sul bordo più esterno della mappa (non il perimetro della base): un tentativo di spostarli "al buio" più lontano dal bordo si è rivelato peggiore, spingendo alcuni punti fuori dall'area valida.
  - Ogni truppa ora manda più tap di quanti gliene servano (draghi: 17 tap per 10 unità, macchina d'assedio: 6 tap per 1 unità), su punti pescati a caso da tutta la zona invece che sempre gli stessi: nei test capitava che alcuni tap non andassero a segno, e le macchine d'assedio hanno regole di piazzamento più rigide dei draghi (serve più margine per trovare un punto valido).
  - Bug corretto: il codice tagliava la lista di punti a N elementi *prima* di mescolarla, quindi con meno tap del totale si riprovava sempre sugli stessi primi punti della lista invece di variare - la macchina d'assedio ci sbatteva contro sistematicamente.
  - Gli eroi usavano un punto di schieramento fisso unico: su basi con mura vicine quel punto cadeva in zona rossa e *nessun* eroe veniva schierato. Ora pescano anche loro dagli stessi punti (validati) delle truppe.
  - Niente scarto di posizione casuale sui punti di schieramento (jitter): essendo calibrati esattamente sul bordo mappa, anche un jitter piccolo rischiava di spingerli oltre il bordo nel vuoto non giocabile (provato dal vivo).
- Randomizzazione leggera: ordine di schieramento mescolato, tempi tra un tap e l'altro variabili invece che fissi. Randomizzazione più spinta (pause di esitazione, sessioni più irregolari) pianificata per la v1.8.
- **Perché:** timore giustificato di ban con un pattern di gioco troppo identico/prevedibile; il deploy incompleto (truppe/eroi/macchina d'assedio mancanti) sprecava metà della potenza dell'attacco ad ogni sessione.
- **Bug trovato in un test dal vivo (non legato al deploy):** se ADB/BlueStacks va giù a metà sessione, ogni attacco falliva subito e il ciclo riprovava ogni 5 secondi fino a fine sessione, mandando un messaggio Telegram di errore ad ogni tentativo (decine in pochi minuti). Ora dopo 3 errori consecutivi il bot si ferma con un solo avviso.
- Nuovo menu **Priorità** nella dashboard: invece di regolare 6 soglie diverse per far scattare la priorità su una risorsa, si può scegliere direttamente "Automatica" (comportamento v1.6, rileva cosa scarseggia in casa) oppure forzare Oro/Elisir/Dark elisir, usando la soglia di attacco già configurata per quella risorsa e saltando del tutto il rilevamento automatico.
- **Bug serio segnalato dal vivo:** durante lo scouting, Tesseract a volte legge una cifra in più che non esiste davvero a schermo (es. "640500" letto come "6400500"), gonfiando il numero e facendo scattare un attacco su una base in realtà sotto soglia. Corretto contando le "macchie" bianche separate nella maschera (ogni cifra del font di gioco è isolata, i caratteri non si toccano mai) e confrontando quel numero con quante cifre ha letto Tesseract: se non corrispondono, la lettura viene scartata invece di rischiare un numero sbagliato. Verificato sulle immagini di debug delle sessioni precedenti (le letture note come corrette hanno il conteggio esatto), ma non ancora su un attacco dal vivo — per questo `main` resta ferma alla versione precedente finché non si conferma con un test reale.

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
