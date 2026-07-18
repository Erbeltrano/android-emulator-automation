# Changelog

Ogni voce spiega cosa è cambiato e **perché**, non solo il cosa — per quello basta `git log`. Il numero di versione è quello in `VERSION` in cima a `BOT_COMPLETO_MAC.py`.

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
