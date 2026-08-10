#!/usr/bin/env python3
"""Bot per il Villaggio Costruttori (secondo villaggio) di Clash of Clans.

Flusso di attacco (doppio raid + schieramento) ad ogni ciclo, più raccolta
elisir dal carretto ogni COLLECT_ELIXIR_EVERY cicli e upgrade mura ogni
WALL_UPGRADE_EVERY cicli (v0.13, su richiesta esplicita dell'utente -
prima la raccolta elisir era ad ogni ciclo e le mura non erano
automatizzate). Tutto calibrato a mano via ADB e documentato in
`secondo_villaggio/README.md`.

Standalone rispetto al bot del villaggio primario (`BOT_COMPLETO_MAC.py`):
i due non possono girare insieme, perché pilotano la stessa istanza
BlueStacks via ADB (un solo "utente" alla volta puo' avere il controllo
dello schermo). Collegato a Telegram (bottone "▶️ Avvia" su "Villaggio
Secondario", vedi `minipc/telegram_relay.py` + task Windows
`CoCBotCostruttori`).

CONFERMATO dal vivo il 2026-07-30 (primo test end-to-end, guidato passo
passo via SSH/ADB con l'utente che guardava lo schermo fisico): un ciclo
completo (doppio raid) ha funzionato al 100% - 200% di danno totale, 3
stelle su entrambi i raid, tutte le unità schierate correttamente
(inclusi gli 8 slot con le truppe bonus del secondo raid).

v0.3: collegato a Telegram (bottone "▶️ Avvia" su "Villaggio Secondario",
vedi `minipc/telegram_relay.py` + task Windows `CoCBotCostruttori`).

v0.3→v0.5: primi test autonomi reali (senza guida passo-passo) hanno
rivelato che il rilevamento "fine raid" basato sul pulsante rosso "Resa"
(sparizione = battaglia finita) era inaffidabile: durante l'animazione di
passaggio tra un raid e l'altro il pulsante a volte restava "rosso" molto
più a lungo del dovuto, facendo credere al bot che la battaglia fosse
ancora in corso e facendolo aspettare fino al tetto di sicurezza
(`BATTLE_WAIT_SECONDS`) anche quando il raid era finito da tempo.

v0.6, fix vero (idea dell'utente): il gioco in realtà passa al raid
successivo in 2-3s se si raggiunge il 100%, non aspetta il timer. Il
segnale affidabile è la scritta in alto: "La battaglia INIZIA tra:"
compare solo quando il prossimo raid è pronto. Letta via OCR
(`_read_top_banner_state()`) al posto del pulsante rosso - vedi
`wait_for_next_screen()`.

CORREZIONE v0.20 (bug vero trovato dal vivo il 2026-08-09): "La battaglia
inizia tra: Ns" NON significa che si può schierare subito, come assunto
qui dalla v0.6 - è ancora una schermata di ANTEPRIMA/scouting
dell'avversario (bottone "Termina battaglia", camera larga, nessuna
truppa/pannello danno), non la vera battaglia (quella ha "Resa", camera
vicina al bordo villaggio, "la battaglia TERMINA tra"). Osservato dal vivo
un countdown "inizia" ancora a 55s dopo l'inizio dello schieramento - un
raid intero sprecato (quasi zero truppe piazzate) prima di capire la causa
vera. Ora si aspetta attivamente che il banner passi a "termina" prima di
schierare sul secondo raid - vedi `run_double_raid()`.

v0.14: l'upgrade mura sceglieva "la prima voce Muro trovata scorrendo
dall'alto" (v0.11-v0.13) assumendo fosse la più economica/al livello più
basso - rivelatosi un bug vero (verificato dal vivo il 2026-08-08: le voci
non sono ordinate per livello nella tendina, e con lo scroll blindamente
riposizionato per conteggio di swipe capitava di cliccare voci sbagliate,
compresi edifici estranei come "Megatesla" durante lo sviluppo - mai
capitato in produzione, solo nei test dal vivo di questa sessione). Ora
scansiona TUTTA la tendina, identifica ogni voce 'Muro' per una "firma"
testuale scroll-indipendente (il suffisso "xN", es. "x130" - non la sua
posizione sullo schermo, che non è mai riproducibile con precisione
sufficiente scorrendo), legge il livello reale di ognuna (titolo "Muro
(liv. N)" mostrato dal gioco stesso) e sceglie sempre quella al livello
più basso - vedi commento generale sopra try_wall_upgrade(). Aggiunto
anche un controllo esplicito con detect_village_type() prima e dopo la
scansione, che interrompe subito il giro con un avviso Telegram se il
villaggio risultasse cambiato nel frattempo.

Limite noto: le voci "Muro" SENZA suffisso (un solo muro rimasto a quel
livello, nessun gruppo) vengono lette ma escluse dalla scelta finale -
verificato dal vivo che "Migliora ancora" non apre la modalità batch su
di esse (il gioco non ha nulla da "aggiungere" con un solo muro
disponibile), quindi il tentativo di acquisto fallirebbe comunque. Se il
livello più basso in assoluto capita di essere un muro singolo, resta
indietro finché non si aggrega a un gruppo (es. un altro muro raggiunge
lo stesso livello) - non blocca la sessione, sceglie semplicemente il
prossimo livello più basso tra le voci con un gruppo reale.

v0.15: bug vero trovato dal vivo il 2026-08-09 - l'utente ha avviato il
bot da Telegram mentre era fuori casa e, controllando lo schermo poco
dopo, l'ha trovato bloccato sul popup "Schede degli incarichi" invece che
in battaglia. Diagnosi dal vivo (log + screenshot ADB): switch_to_village
falliva (il tap sulla barca verso il Villaggio Costruttori non trovava più
la barca), ma il valore di ritorno non veniva controllato in main() - il
bot procedeva comunque al ciclo di attacco usando le coordinate del
Villaggio Costruttori mentre il gioco era rimasto sul primario, aprendo
per sbaglio quel popup invece di attaccare (nessun danno reale, verificato
su oro/elisir/trofei invariati). Causa radice del tap fallito: il dezoom
automatico della camera (aggiunto l'8/8, DOPO che le coordinate della
barca erano state calibrate il 4/8) ha cambiato lo stato zoom/pan con cui
il bot parte, spostando dove si trova la barca sullo schermo - vedi
commento su BOAT_TO_BUILDER_PAN/POINT. Due fix: (1) coordinate della
barca ricalibrate dal vivo nel nuovo stato dezoomato (2) main() ora si
ferma con un avviso Telegram se switch_to_village fallisce, invece di
proseguire alla cieca sul villaggio sbagliato.

v0.16: bug vero trovato dal vivo lo stesso giorno, subito dopo il fix v0.15
- l'utente ha avviato il bot, un primo ciclo (2 raid) è andato a buon fine,
ma il secondo si è bloccato di nuovo sul popup "Schede degli incarichi".
Diagnosi dal vivo: NON un problema di villaggio sbagliato stavolta (il
bot era correttamente sul Villaggio Costruttori, verificato via
screenshot) - i tap "a vuoto" pensati per chiudere un eventuale popup
"Bonus stella!" (STAR_BONUS_OK_BUTTON, coordinate fisse) hanno invece
aperto quel badge evento stagionale, presente anche su questo villaggio
e non solo sul primario. Il ciclo proseguiva comunque alla cieca verso
"Attacco!"/"Cerca!" con quel popup ancora aperto, restando bloccato ad
aspettare la fine di una battaglia mai iniziata. Fix: `_ensure_home_or_recover()`
verifica `is_home_screen()` dopo la pulizia di fine ciclo e, se non siamo
sulla home, tocca una zona vuota della mappa per deselezionare eventuali
pannelli aperti (stessa tecnica di `_close_wall_panel()`) - **non** il tasto
Indietro Android, scartato dopo un test dal vivo pericoloso lo stesso
giorno: premuto un paio di volte sulla home screen fa comparire il dialog
nativo "Vuoi uscire dal gioco?", un rischio reale di chiudere il gioco per
sbaglio (vedi commento su `_ensure_home_or_recover()`). Se dopo 3 tentativi
siamo ancora bloccati, il ciclo viene contato come fallito (arriva al tetto
di sicurezza `MAX_CONSECUTIVE_ERRORS` invece di restare bloccato in
silenzio).

v0.17: il bug del popup imprevisto (v0.16) si è ripresentato lo stesso
giorno nonostante il fix, e l'utente ha chiesto di analizzare OGNI singolo
tap per trovare la causa vera invece di continuare a scoprire sintomi.
Diagnosi con screenshot di debug dopo ogni tap sospetto (RETURN_HOME_BUTTON,
i due STAR_BONUS_OK_BUTTON), poi un run reale supervisionato: trovato che
STAR_BONUS_OK_BUTTON (960, 838) veniva tappato SEMPRE, incondizionatamente,
"a vuoto se non serve" - ma è una coordinata sulla MAPPA di gioco (non un
elemento di UI fisso), quindi se un edificio (es. un muro) si trova lì
sotto per via della posizione della camera in quel momento (stesso problema
di fondo già noto per la barca), il tap apre il suo pannello invece di non
fare nulla. Osservato dal vivo un caso concreto e serio: un primo tap ha
aperto il pannello "Muro (liv. 8)", il secondo tap (stesso punto, ora sul
pannello aperto) è caduto sul pulsante "Migliora" (oro), aprendo un vero
dialog di conferma spesa "Portare al livello 9? 640.000 Oro" - a un tap di
distanza da una spesa reale non voluta (nessuna spesa avvenuta, chiuso in
tempo durante la diagnosi). Fix: entrambi i tap STAR_BONUS_OK_BUTTON (a
inizio E a fine ciclo) ora scattano solo se `is_home_screen()` dice che
c'è davvero qualcosa da chiudere, invece di sempre "a vuoto" - se non serve
non si tocca affatto quel punto.

ATTENZIONE - parti ancora da consolidare:
- Il rilevamento raid1→raid2/risultati combina OCR (`TOP_BANNER_REGION`)
  e un pixel singolo (`RESULTS_SCREEN_CHECK_POINT`), verificati sugli
  screenshot reali del 2026-07-30 ma non ancora su molti cicli diversi -
  se una base ha una UI/tema diverso potrebbe servire ricalibrare.
- Lo swipe camera (`CAMERA_SWIPE_START`/`END`) è stato aggiustato più
  volte lo stesso giorno e potrebbe ancora non essere ottimale su ogni
  base - vedi i commenti lì per la cronologia dei tentativi.
- Nessun controllo "siamo tornati al villaggio" dopo i tap finali: si
  segue solo la sequenza calibrata a mano.
"""
import argparse
import itertools
import os
import random
import re
import shutil
import subprocess
import sys
import time

import numpy as np
import cv2
import pytesseract
import requests  # per Telegram

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VERSION = "0.21"


def find_tesseract_cmd():
    """Stessa logica di `find_tesseract_cmd()` nel bot principale."""
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Tesseract non trovato (vedi README del bot principale).")


pytesseract.pytesseract.tesseract_cmd = find_tesseract_cmd()

# Ogni riga di log ha l'ora esatta: senza, capire DOVE va perso tempo in un
# ciclo (es. segnalato dal vivo: sembra restare fermo per oltre un minuto
# prima del secondo raid) richiederebbe di rileggere lo screen a occhio
# invece di guardare i minuti/secondi reali tra una riga e l'altra del log.
_builtin_print = print


def print(*args, **kwargs):
    _builtin_print(f"[{time.strftime('%H:%M:%S')}]", *args, **kwargs)

# ==========================
# TELEGRAM (stesse credenziali del bot principale, vedi README/cred)
# ==========================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    sys.exit(
        "Errore: variabili d'ambiente TELEGRAM_BOT_TOKEN e/o TELEGRAM_CHAT_ID mancanti.\n"
        "Stesse credenziali del bot principale (vedi README/cred): caricale prima di avviare."
    )


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        print("[TELEGRAM] Status:", resp.status_code)
    except Exception as e:
        print("[TELEGRAM] Errore invio:", e)


def send_telegram_photo(path: str, caption: str = ""):
    """Vedi BOT_COMPLETO_MAC.py per il contesto - stesso helper, duplicato
    qui per restare uno script autonomo."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(path, "rb") as f:
            resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"photo": f}, timeout=20)
        print("[TELEGRAM] sendPhoto status:", resp.status_code)
    except Exception as e:
        print("[TELEGRAM] Errore invio foto:", e)


# ==========================
# ADB (stessa infrastruttura del bot principale - duplicata qui per
# restare uno script autonomo/deployabile da solo, come BOT_COMPLETO_MAC.py)
# ==========================

def find_adb_cmd():
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        "/Applications/BlueStacks.app/Contents/MacOS/hd-adb",
        r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("adb non trovato (vedi README del bot principale).")


ADB_CMD = find_adb_cmd()


def adb(*args, device=None, timeout=15):
    cmd = [ADB_CMD]
    if device:
        cmd += ["-s", device]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)


def find_device():
    result = adb("devices")
    lines = result.stdout.decode(errors="ignore").strip().splitlines()[1:]
    for line in lines:
        if line.strip().endswith("device"):
            return line.split()[0]
    raise RuntimeError("Nessun device ADB trovato. BlueStacks avviato? ADB abilitato?")


DEVICE = find_device()
print(f"[ADB] Device connesso: {DEVICE}")


def _adb_retry(func, retries=3, retry_delay=1.0):
    """Stesso pattern di `_adb_retry()` nel bot principale: un singolo
    intoppo ADB transitorio (tipico post-risveglio a freddo) non deve far
    fallire subito l'intero ciclo."""
    last_error = None
    for attempt in range(retries):
        try:
            return func()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(retry_delay)
    raise last_error


def adb_tap(x, y):
    _adb_retry(lambda: adb("shell", "input", "tap", str(x), str(y), device=DEVICE))


def adb_swipe(x1, y1, x2, y2, duration_ms=600):
    _adb_retry(lambda: adb(
        "shell", "input", "swipe",
        str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        device=DEVICE,
    ))




def adb_screenshot(retries=3, retry_delay=1.0):
    """Stesso pattern di `adb_screenshot()` nel bot principale: ritenta in
    caso di intoppo ADB transitorio (tipico post-risveglio a freddo)."""
    last_error = None
    for attempt in range(retries):
        try:
            result = adb("exec-out", "screencap", "-p", device=DEVICE)
            img_array = np.frombuffer(result.stdout, dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError("Screenshot ADB non decodificabile (screencap fallito?).")
            return frame
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, cv2.error) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(retry_delay)
    raise last_error


# ==========================
# COORDINATE (calibrate a mano via ADB il 2026-07-27, vedi README)
# ==========================
ATTACK_BUTTON = (110, 990)          # "Attacco!" nella home del Villaggio Costruttori
SEARCH_BUTTON = (1425, 710)         # "Cerca!" nel popup "Inizia attacco"
RETURN_HOME_BUTTON = (960, 910)     # "Torna al villaggio" a fine dei due raid
STAR_BONUS_OK_BUTTON = (960, 838)   # OK sul popup extra "Bonus stella!" (se compare) - NON PIÙ USATO
                                     # da v0.18 (era una coordinata sulla mappa, rischio di tap su un
                                     # edificio vero - vedi commento in run_double_raid()), lasciato solo
                                     # come riferimento storico

# Carretto elisir (ricompense dalle difese, cap 1.600.000): flusso
# documentato in secondo_villaggio/README.md (calibrato e testato con soldi
# veri il 2026-07-27), ri-verificato dal vivo il 2026-07-31 con le stesse
# coordinate (+1.600.000 elisir esatti, confermato confrontando il saldo
# prima/dopo). Non è la barra risorse della home di default: bisogna prima
# pannare la camera verso l'alto per farlo comparire sulla destra.
CART_SWIPE_UP = ((960, 300), (960, 700))
ELIXIR_CART_POINT = (1375, 400)
CART_TAKE_BUTTON = (1410, 910)      # "Prendi" - sicuro anche senza nuove ricompense
CART_CLOSE_BUTTON = (1620, 105)     # X in alto a destra del popup

# Popup non documentato prima d'ora, comparso in modo consistente ad ENTRAMBI
# i tentativi di attacco del test dal vivo del 2026-07-30 (subito dopo
# "Cerca!"): "Disposizione difensiva ostruita" - riguarda la disposizione
# difensiva della PROPRIA base (ostacoli non rimossi), non l'avversario. Il
# tap qui è "a vuoto" se il popup non compare (nessun elemento cliccabile
# della schermata sottostante corrisponde a queste coordinate, stesso
# principio già usato per CONFIRM_END_BATTLE_BUTTON nel bot principale).
OBSTRUCTED_LAYOUT_OK_POINT = (1180, 695)

# Camera: non è un vero zoom (impossibile su questo device, vedi README),
# solo uno swipe fisso che porta la vista in una posizione ripetibile -
# confermato coerente su basi diverse.
CAMERA_SWIPE_START = (960, 700)
CAMERA_SWIPE_END = (960, 250)
CAMERA_SWIPE_DURATION_MS = 600
# Calibrato dal vivo il 2026-07-30 (non a occhio, più iterazioni):
# (960,600)->(960,300) [delta -300px] schierava solo parte delle truppe.
# (960,750)->(960,150) [delta -600px, doppio] si è rivelato ECCESSIVO: la
# base usciva quasi del tutto dallo schermo in alto. (960,650)->(960,300)
# [delta -350px] ha dato uno schieramento completo su una base (200%/3
# stelle) ma su una base diversa, nella prima esecuzione autonoma reale,
# l'utente ha visto dal vivo che non bastava ancora ("voglio che arrivi sui
# bordi"). Alzato ulteriormente a -450px come via di mezzo tra il valore
# che ha funzionato (-350) e quello che ha overshootato (-600). Se ancora
# insufficiente/eccessivo su altre basi, il metodo della griglia
# (screenshot + overlay) resterebbe l'opzione più affidabile per una
# calibrazione definitiva invece di altri aggiustamenti alla cieca.
#
# Durata riportata a 600ms (era stata alzata a 1600ms su richiesta
# esplicita, poi l'utente ha chiesto di velocizzare la transizione al
# secondo raid): la durata del drag non cambia la posizione finale della
# camera (è un drag 1:1, non a inerzia), solo la velocità - riducendola si
# risparmia circa 1s ad ogni deploy_wave() senza toccare la distanza.

# Barra unità in basso: eroe + fino a 8 slot truppe (include gli eventuali
# 2 slot bonus del solo secondo raid). Tappare uno slot vuoto non ha
# alcun effetto (stesso comportamento del bot principale), quindi si
# tocca sempre la lista intera invece di contare le unità reali presenti.
UNIT_BAR_Y = 990
UNIT_SLOTS_X = [195, 355, 515, 675, 835, 995, 1155, 1315, 1475]

# Punti di sgancio fissi, calibrati col metodo della griglia (celle H4/I3):
# alternati tra le unità, non serve un punto diverso per ognuna.
DEPLOY_POINTS = [(1200, 720), (1360, 560)]

WAIT_BEFORE_DEPLOY = 3.0  # dopo "Cerca!": NON aspettare il countdown pieno
                          # (~40s) - il tempo di battaglia rischia di scadere
                          # prima di finire lo schieramento (visto dal vivo)
ABILITY_RETAP_DELAY = 2.0  # attesa prima di ri-toccare le icone per le abilità
INTER_TAP_DELAY_RANGE = (0.2, 0.4)

# Tetto massimo di sicurezza (il timer di battaglia del Villaggio
# Costruttori è fisso, 2:30): rete di sicurezza se il rilevamento attivo
# sotto (BATTLE_BUTTON_CHECK_POINT) smettesse di funzionare per qualche
# motivo, non più il meccanismo principale (v0.3).
BATTLE_WAIT_SECONDS = 155.0
RAID2_PREVIEW_MAX_WAIT = 70.0  # v0.20: tetto massimo per aspettare che l'anteprima del
                                # secondo raid ("la battaglia inizia tra:") passi alla vera
                                # battaglia ("termina tra") - osservato dal vivo fino a 55s
                                # di countdown ancora presenti, margine di sicurezza sopra

# v0.3: rilevamento attivo di fine battaglia invece di un'attesa fissa.
# Nel primo test autonomo reale (2026-07-30) l'attesa fissa ha fatto
# sprecare minuti interi: la battaglia finiva molto prima (100% raggiunto
# in fretta) ma il bot restava fermo prima di accorgersene.
#
# v0.6, fix del vero problema (spiegato dall'utente dopo aver visto v0.3 dal
# vivo): NON è che il gioco aspetta i 2:30 pieni per passare al secondo raid
# - se si arriva a 3 stelle in 20s, il gioco passa da solo al secondo raid
# in 2-3s. Il problema era il rilevamento: il pulsante rosso "Resa"
# (`BATTLE_BUTTON_CHECK_POINT`, ora sostituito) a volte restava "rosso"
# molto più a lungo del dovuto durante l'animazione di passaggio tra un
# raid e l'altro, facendo credere al bot che la battaglia fosse ancora in
# corso. Sostituito con un segnale diretto suggerito dall'utente: leggere
# via OCR la scritta in alto - "La battaglia INIZIA tra:" compare SOLO
# quando il prossimo raid è pronto (verificato: durante "termina tra" -
# battaglia in corso - OCR legge "termina", mai "inizia"). Usata per
# capire CHE il raid successivo esiste, non più per decidere quando
# schierare - vedi correzione v0.20 sopra e in run_double_raid(): "inizia"
# è ancora un'anteprima, bisogna aspettare che diventi "termina" prima di
# schierare.
TOP_BANNER_REGION = {"left": 650, "top": 10, "width": 650, "height": 90}

# `RESULTS_SCREEN_CHECK_POINT` (195,990, dove normalmente c'è l'icona
# dell'eroe nella barra unità): nero pieno (somma RGB < 30) SOLO sulla
# schermata finale "Truppe utilizzate / Ricompense / Torna al villaggio" -
# colorato (icona truppa o ritratto eroe) in ogni altro stato (countdown,
# battaglia). Resta invariato da v0.3, ancora il segnale più affidabile
# trovato per la schermata di fine dei due raid.
RESULTS_SCREEN_CHECK_POINT = (195, 990)
RESULTS_SCREEN_MAX_BRIGHTNESS = 30
BATTLE_POLL_INTERVAL = 1.5

MAX_CONSECUTIVE_ERRORS = 3

# ==========================
# CONTROLLO/CAMBIO VILLAGGIO (stesso meccanismo del bot principale)
# ==========================
# Clash of Clans resta sull'ultimo villaggio visitato tra un avvio e
# l'altro: se il bot del villaggio primario ha lasciato il gioco aperto lì,
# questo bot partirebbe alla cieca sullo schermo sbagliato. Coordinate e
# soglie calibrate dal vivo il 2026-07-30 con screenshot reali (vedi gli
# stessi commenti in BOT_COMPLETO_MAC.py, identici qui per costruzione).
HOME_CHECK_REGION = {"left": 40, "top": 1038, "width": 160, "height": 17}  # striscia arancione del
                     # pulsante "Attacco!", sotto il testo e sopra il bordo
HOME_CHECK_MIN_DIFF = 50
# v0.18: HOME_CHECK_POINT (singolo pixel, (135, 1010)) sostituito con una
# REGIONE dopo un bug vero trovato dal vivo il 2026-08-09: quel pixel
# cadeva esattamente su un contorno nero della scritta "Attacco!" in certi
# stati di zoom (r-b praticamente 0 invece che arancione), facendo
# risultare is_home_screen() False su una schermata home in realtà
# perfettamente pulita - falso negativo che ha fatto fallire
# _ensure_home_or_recover() e bloccare/interrompere cicli buoni per errore.
# La striscia qui sopra (sotto il testo, sopra il bordo del pulsante) è
# stata verificata su 4 screenshot reali diversi (villaggio primario e
# Costruttore, stati di zoom diversi): r-b medio sempre 71-74, mai vicino
# alla soglia - molto più tollerante di un singolo pixel a piccoli
# spostamenti di rendering del testo.
# v0.8 (2026-08-04): BOAT_TO_BUILDER_POINT era un tap diretto (badge fisso
# sull'acqua) - ma un nuovo badge dell'evento stagionale ("Scheda degli
# incarichi", icona con countdown "27g 12h", non presente al momento della
# calibrazione originale) si è aggiunto sopra quel punto esatto della UI,
# intercettando il tap prima che arrivasse alla barca sottostante:
# switch_to_village("costruttore") falliva sempre (2 tentativi, "Cambio
# fallito"), scoperto dal vivo. Stesso fix già usato per il tragitto di
# ritorno: pan della camera per liberare la barca, poi tap.
#
# Ricalibrato dal vivo il 2026-08-09 (v0.15): il dezoom automatico della
# camera (windows/dezoom_camera.ps1, integrato negli script di avvio l'8/8,
# DOPO che queste coordinate erano già calibrate il 4/8) cambia lo stato
# zoom/pan con cui il bot parte - le vecchie coordinate non trovavano più la
# barca (bug vero osservato dal vivo dall'utente: switch_to_village falliva,
# il bot procedeva comunque all'attacco sul villaggio sbagliato, finendo
# bloccato sul popup "Schede degli incarichi").
#
# Scoperta importante durante la ricalibrazione dal vivo: lo zoom/pan della
# camera dopo un riavvio a freddo NON è deterministico come si pensava (il
# commento di dezoom_camera.ps1 assumeva che il gesto portasse sempre allo
# stesso zoom minimo) - osservati dal vivo lo stesso giorno DUE stati
# diversi con la barca in posizioni molto diverse sullo schermo (uno più
# zoomato-indietro, uno più vicino), senza aver ancora capito la causa
# esatta (possibile interazione con eventi in-game come una notifica di
# attacco subito, non confermato). Fix pragmatico invece di inseguire la
# causa esatta: BOAT_TO_BUILDER/PRIMARY_CANDIDATES prova più coppie
# pan+punto in sequenza (una per ogni stato osservato dal vivo), verificando
# con detect_village_type() dopo ognuna - se in futuro emerge un terzo stato
# diverso, aggiungere qui un'altra voce invece di ricalibrare da zero.
# Soluzione più robusta ma non ancora implementata: cercare la barca via
# template matching (cv2.matchTemplate) invece di coordinate fisse, così da
# non dipendere da un numero chiuso di stati noti - lasciata per una
# sessione futura dedicata.
BOAT_TO_BUILDER_CANDIDATES = [
    {"pan": None, "point": (740, 430)},    # stato "zoomato indietro" (dezoom pulito)
    {"pan": None, "point": (460, 860)},    # stato "più vicino" osservato dopo un giro completo
]
BOAT_TO_PRIMARY_CANDIDATES = [
    {"pan": ((1400, 300), (700, 700)), "point": (1720, 700)},  # stato "zoomato indietro"
    {"pan": None, "point": (1773, 397)},                        # stato "più vicino"
]
VILLAGE_CHECK_REGION = {"left": 600, "top": 0, "width": 700, "height": 15}
VILLAGE_CHECK_GB_THRESHOLD = 20

# v0.21 (2026-08-10): bug vero trovato dal vivo lo stesso giorno - l'utente
# ha segnalato che il Villaggio Costruttori "non partiva" quando avviato da
# fuori casa. Diagnosi via log reale (bot_costruttori_log.txt sul PC
# Windows): switch_to_village("costruttore") ha provato ENTRAMBI i
# candidati sopra e ha mancato la barca con tutti e due - ricalibrando dal
# vivo nella stessa sessione (screenshot ADB reali), la barca si trovava
# quel giorno in un TERZO stato, vicino al secondo candidato ma abbastanza
# spostato da mancare comunque il tap puntuale ((420,900) confermato
# funzionante contro (460,860) del candidato - solo 40-65px di differenza,
# ma sufficienti a mancare la hitbox). Confema dal vivo il tema ricorrente
# di tutta questa serie di sessioni: la posizione della barca non è
# deterministica tra un riavvio e l'altro, e aggiungere sempre nuovi
# candidati fissi è rincorrere sintomi all'infinito.
#
# Fix vero: invece di tappare alla cieca il punto del candidato, si cerca
# la barca via cv2.matchTemplate (template ritagliato da uno screenshot
# reale, boat_to_builder_ref.png/boat_to_primary_ref.png) in una finestra
# di ricerca centrata sul punto del candidato (non tutto lo schermo, per
# velocità e per evitare falsi positivi altrove) - così un piccolo
# spostamento della barca rispetto alla posizione calibrata (come quello
# osservato oggi) viene comunque trovato. Provato anche a scale diverse
# (BOAT_MATCH_SCALES) per tollerare un po' di variazione di zoom, non solo
# di posizione - non ancora verificato dal vivo su un vero stato di zoom
# diverso (oggi ne è stato osservato solo uno), quindi resta un
# miglioramento best-effort. Se il template match non trova nulla sopra
# BOAT_MATCH_MIN_CONFIDENCE, si ricade sul vecchio tap puntuale esatto del
# candidato (nessuna regressione rispetto a prima).
BOAT_MATCH_SCALES = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15)
BOAT_MATCH_MIN_CONFIDENCE = 0.55
BOAT_MATCH_SEARCH_MARGIN = 160  # finestra di ricerca: punto del candidato +/- questo margine
BOAT_TO_BUILDER_REF_FILE = "boat_to_builder_ref.png"
BOAT_TO_PRIMARY_REF_FILE = "boat_to_primary_ref.png"
_boat_to_builder_ref = cv2.imread(BOAT_TO_BUILDER_REF_FILE)
_boat_to_primary_ref = cv2.imread(BOAT_TO_PRIMARY_REF_FILE)


def _find_boat(frame, template, around_point, margin=BOAT_MATCH_SEARCH_MARGIN):
    """Cerca `template` dentro una finestra centrata su `around_point` (+/-
    margin), provando le scale in BOAT_MATCH_SCALES per tollerare un po' di
    variazione di zoom. Ritorna il centro assoluto del miglior match se
    sopra BOAT_MATCH_MIN_CONFIDENCE, altrimenti None (il chiamante ricade
    sul tap puntuale del candidato)."""
    if template is None:
        return None
    px, py = around_point
    l = max(0, px - margin)
    t = max(0, py - margin)
    r = min(frame.shape[1], px + margin)
    b = min(frame.shape[0], py + margin)
    crop = frame[t:b, l:r]
    th, tw = template.shape[:2]
    best_val, best_loc, best_size = -1.0, None, None
    for scale in BOAT_MATCH_SCALES:
        sw, sh = max(1, int(tw * scale)), max(1, int(th * scale))
        if sw >= crop.shape[1] or sh >= crop.shape[0]:
            continue
        resized = cv2.resize(template, (sw, sh))
        result = cv2.matchTemplate(crop, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val, best_loc, best_size = max_val, max_loc, (sw, sh)
    if best_val < BOAT_MATCH_MIN_CONFIDENCE:
        return None
    return (l + best_loc[0] + best_size[0] // 2, t + best_loc[1] + best_size[1] // 2)


def _home_pixel_says_home():
    frame = adb_screenshot()
    l, t = HOME_CHECK_REGION["left"], HOME_CHECK_REGION["top"]
    w, h = HOME_CHECK_REGION["width"], HOME_CHECK_REGION["height"]
    region = frame[t:t + h, l:l + w].astype(np.int32)
    r_mean = region[:, :, 2].mean()
    b_mean = region[:, :, 0].mean()
    return (r_mean - b_mean) > HOME_CHECK_MIN_DIFF


def is_home_screen():
    """True se siamo su una schermata home (di uno dei due villaggi, non
    in ricerca/battaglia) - verificato dal vivo che funziona identico su
    entrambi (stesso pulsante "Attacco!" arancione in entrambi i casi)."""
    if not _home_pixel_says_home():
        return False
    time.sleep(0.4)
    return _home_pixel_says_home()


RECOVERY_EMPTY_MAP_POINT = (300, 200)  # stessa zona rocciosa vuota di WALL_EMPTY_MAP_POINT più sotto


def _ensure_home_or_recover(max_attempts=3):
    """Bug vero trovato dal vivo il 2026-08-09 (v0.15): dopo un ciclo, i tap
    "a vuoto" per chiudere un eventuale popup 'Bonus stella!' (STAR_BONUS_OK_BUTTON,
    a coordinate fisse) possono invece aprire per sbaglio un popup diverso e
    imprevisto (es. il badge evento stagionale "Schede degli incarichi",
    presente anche sul Villaggio Costruttori, non solo sul primario) - il
    ciclo proseguiva comunque alla cieca, finendo bloccato ad aspettare la
    fine di una battaglia mai iniziata.

    ATTENZIONE - la prima versione di questo fix usava il tasto Indietro
    Android (KEYCODE_BACK) per chiudere qualunque cosa fosse aperta, in modo
    generico. Scartato dopo un test dal vivo pericoloso lo stesso giorno:
    premuto un paio di volte sulla home screen, il tasto Indietro fa
    comparire il dialog nativo "Vuoi uscire dal gioco?" - un rischio reale
    di chiudere il gioco per sbaglio se usato alla cieca in un loop. Usa
    invece un tap su una zona rocciosa vuota fuori dalla base
    (RECOVERY_EMPTY_MAP_POINT, stessa tecnica già collaudata da
    _close_wall_panel() per deselezionare pannelli edificio) - non chiude un
    popup a schermo intero come "Schede degli incarichi" (serve la sua X),
    ma è innocuo se non serve e chiude in modo affidabile i pannelli
    edificio aperti per sbaglio (es. da STAR_BONUS_OK_BUTTON finito su un
    edificio). Se dopo i tentativi non risultiamo ancora su una home
    screen, meglio fermarsi con un errore (il chiamante lo tratta come
    ciclo fallito, vedi main()) che rischiare altre azioni alla cieca."""
    for _ in range(max_attempts):
        if is_home_screen():
            return True
        print("[RECOVERY] Non risultiamo su una home screen, tocco una zona vuota della mappa...")
        adb_tap(*RECOVERY_EMPTY_MAP_POINT)
        time.sleep(1.2)
    return is_home_screen()


def detect_village_type(frame=None):
    if frame is None:
        frame = adb_screenshot()
    l, t = VILLAGE_CHECK_REGION["left"], VILLAGE_CHECK_REGION["top"]
    w, h = VILLAGE_CHECK_REGION["width"], VILLAGE_CHECK_REGION["height"]
    crop = frame[t:t + h, l:l + w].astype(np.int32)
    b_mean = crop[:, :, 0].mean()
    g_mean = crop[:, :, 1].mean()
    return "primario" if (g_mean - b_mean) > VILLAGE_CHECK_GB_THRESHOLD else "costruttore"


def switch_to_village(target):
    """Prova ogni candidato pan+punto in BOAT_TO_BUILDER/PRIMARY_CANDIDATES
    (uno per ogni stato di zoom/pan osservato dal vivo - vedi commento sulle
    costanti) finché uno funziona o si esauriscono i tentativi.

    v0.21: per ogni candidato, prima di tappare il punto esatto, cerca la
    barca via template matching in una finestra centrata su quel punto (vedi
    _find_boat) - se la trova (anche spostata di un po' rispetto al punto
    calibrato), tappa la posizione trovata invece del punto fisso. Se non la
    trova, ricade sul vecchio comportamento (tap del punto esatto)."""
    candidates = BOAT_TO_BUILDER_CANDIDATES if target == "costruttore" else BOAT_TO_PRIMARY_CANDIDATES
    template = _boat_to_builder_ref if target == "costruttore" else _boat_to_primary_ref
    for i, candidate in enumerate(candidates):
        current = detect_village_type()
        if current == target:
            if i > 0:
                print(f"[VILLAGGIO] Ora siamo su '{target}'.")
            return True

        print(f"[VILLAGGIO] Siamo su '{current}', serve '{target}': tocco la barca (candidato {i + 1}/{len(candidates)})...")
        pan, point = candidate["pan"], candidate["point"]
        if pan is not None:
            adb_swipe(pan[0][0], pan[0][1], pan[1][0], pan[1][1])
            time.sleep(0.8)

        found = _find_boat(adb_screenshot(), template, point)
        if found is not None:
            print(f"[VILLAGGIO] Barca trovata via template match a {found} (candidato puntava a {point}).")
            adb_tap(*found)
        else:
            adb_tap(*point)
        time.sleep(4.0)

    # v0.9: stesso fix di BOT_COMPLETO_MAC.py - il controllo veniva fatto
    # solo PRIMA di ogni tap, mai dopo l'ultimo, quindi un cambio riuscito
    # solo all'ultimo tentativo veniva comunque riportato come fallito.
    if detect_village_type() == target:
        print(f"[VILLAGGIO] Ora siamo su '{target}'.")
        return True

    print(f"[VILLAGGIO] Cambio fallito dopo {len(candidates)} tentativi, siamo ancora su '{detect_village_type()}'.")
    return False


# ==========================
# UPGRADE MURA (v0.11) - stesso meccanismo del villaggio primario
# (BOT_COMPLETO_MAC.py: tendina badge costruttore + batch "Aggiungi mura
# +1"), verificato dal vivo il 2026-08-04 che il Villaggio Costruttori usa
# la STESSA UI (corregge una vecchia ipotesi di questo file/README: NON è
# un tap diretto sul segmento di muro sulla mappa). Differenze rispetto al
# villaggio primario:
# - L'upgrade è sempre istantaneo ("Tempo miglioramento: Zero" verificato
#   dal vivo), quindi non serve controllare un costruttore libero come nel
#   primario (has_free_builder() lì esiste solo come euristica "buon
#   momento per investire", qui non ha senso).
# - Il costo delle mura è mostrato SOLO in oro nella tendina (mai elisir in
#   questo villaggio) - ma il pannello del singolo muro offre anche una
#   seconda valuta scoperta per caso il 2026-08-04, "Anello da mura" (icona
#   ad anello dorato, costo "1"): scelta esplicita di NON toccarla mai in
#   automatico (oggetto raro/non rinnovabile, mai richiesto dall'utente) -
#   si usa sempre e solo il pulsante oro.
# - Possono comparire PIÙ voci "Muro" contemporaneamente nella tendina
#   (account rush, livelli di mura disomogenei) - a differenza del
#   villaggio primario dove ce n'è sempre una sola. Fino alla v0.13 si
#   prendeva semplicemente la PRIMA voce "Muro" trovata scorrendo dall'alto
#   (nessuna lettura di cifre, lo stesso costo era già noto per essere
#   inaffidabile via OCR - "204 000" letto "#204 000", "8 500" letto "@38"
#   a seconda dello sfondo semi-trasparente, testato offline il 2026-08-04)
#   - **rivelatosi un bug vero**: verificato dal vivo il 2026-08-08 che le
#   voci "Muro" NON sono vicine tra loro né ordinate per costo/livello
#   nella tendina (es. visto dal vivo: livelli 3, 4, 5, 6 sparsi in punti
#   diversi della lista, per niente in quest'ordine scorrendo) - "la prima
#   trovata" finiva quindi per scegliere un gruppo praticamente a caso,
#   spesso non quello più indietro, esattamente il sintomo lamentato
#   dall'utente (alcune mura spinte avanti, altre mai toccate).
#
#   Fix (v0.14): niente più bisogno di indovinare dal costo o dalla
#   posizione nella lista. Selezionando una voce, il gioco mostra da solo
#   un titolo grande "Muro (liv. N)" sopra i pulsanti - un numero piccolo e
#   pulito, molto più affidabile del testo dei costi (niente separatori
#   delle migliaia, niente sfondo semi-trasparente disomogeneo). Un giro
#   ora scansiona TUTTA la tendina, legge il livello vero di ogni voce
#   "Muro" trovata (_read_wall_level(), calibrato dal vivo il 2026-08-08 su
#   4 livelli reali diversi: 3/4/5/6, tutti letti correttamente), sceglie
#   quella al livello più basso, e solo su quella esegue il batch di
#   upgrade - così tutte le mura avanzano di pari passo invece che a caso.
#
#   Scoperta collaterale della stessa sessione: il costo NON è sempre e
#   solo in oro come si pensava ("Muro x5" mostrava 320.000 in ELISIR nella
#   tendina, e il suo pannello offriva sia "Migliora" oro CHE elisir allo
#   stesso prezzo, 6 pulsanti invece dei soliti 4-5) - il codice continua a
#   pagare sempre e solo in oro (comportamento invariato, scelta esplicita
#   di sempre), ma un'eventuale voce "Muro" col solo pagamento in elisir
#   fallirebbe in modo sicuro sui controlli esistenti (nessuna spesa, vedi
#   try_wall_upgrade) invece di spendere la valuta sbagliata.
BUILDER_BADGE_POINT_BB = (1115, 65)  # badge "Miglioramenti", vista di default del Villaggio Costruttori
WALL_DROPDOWN_REGION = {"left": 870, "top": 150, "width": 540, "height": 650}
WALL_DROPDOWN_SCROLL = ((1140, 700), (1140, 300))
WALL_MAX_SCROLL_ATTEMPTS = 8
WALL_LIST_MAX_SCROLL_STEPS = 10  # scansione completa della tendina (_scan_all_wall_entries):
                                  # verificato dal vivo il 2026-08-08 che ~6 swipe bastano per
                                  # raggiungere il fondo della lista attuale, margine di sicurezza
                                  # per quando l'account sblocca altri edifici in futuro
WALL_LEVEL_TITLE_REGION = {"left": 650, "top": 670, "width": 650, "height": 75}  # titolo grande
                                  # "<Edificio> (liv. N)" che compare sopra i pulsanti dopo aver
                                  # selezionato una voce - vedi _read_wall_level
WALL_LEVEL_MAX_PLAUSIBLE = 20  # livello massimo plausibile per un muro - oltre questo la lettura
                                  # OCR viene scartata come sbagliata (vedi _read_wall_level)
WALL_EMPTY_MAP_POINT = (300, 200)  # zona rocciosa vuota fuori dalla base - tap per chiudere in modo
                                  # affidabile qualunque pannello/tendina aperta, usato nella fase di
                                  # esplorazione qui sotto. Più affidabile di deselect_all_bb() (doppio
                                  # tap sulla barra oro) per uso ripetuto: verificato dal vivo il
                                  # 2026-08-08 che quest'ultimo a volte non chiude nulla.
WALL_ACTION_BAR_REGION = {"left": 300, "top": 760, "width": 1350, "height": 220}
WALL_COST_LABEL_OFFSET = (0, -73)   # dal centro del pulsante "Migliora" al centro dell'etichetta di costo -
                                     # ricalibrato dal vivo il 2026-08-08 (vedi _wall_cost_is_red): l'offset -55
                                     # ereditato dal villaggio primario catturava solo il bordo inferiore del
                                     # numero, causando un falso negativo reale (34 mura, costo 4.080.000 contro
                                     # 3.976.404 disponibili, mai rilevato come rosso)
WALL_COST_LABEL_SIZE = (90, 18)
WALL_MAX_ADD_TAPS = 60
GENERIC_DIALOG_CONFIRM_POINT = (1170, 693)  # pulsante "OK" verde del dialog "Migliora le mura" /
                                             # "Vuoi davvero migliorare le mura selezionate per N Oro?"
                                             # (Annulla/OK) - NON lo stesso dialog "Portare al livello
                                             # N?" del muro singolo (quello ha un pulsante diverso a
                                             # (965,945), ma il flusso qui passa sempre da "Migliora
                                             # ancora"/batch anche per 1 solo muro, quindi serve solo
                                             # questo punto. Bug reale trovato dal vivo il 2026-08-04:
                                             # col punto sbagliato (965,945, copiato per errore dal
                                             # dialog del muro singolo) il tap cadeva a vuoto - nessuna
                                             # spesa avveniva, ma il codice non se ne accorgeva e
                                             # riportava comunque "confermato" (falso positivo). Fix
                                             # verificato dal vivo: oro sceso esattamente dell'importo
                                             # atteso (1.360.208 -> 136.208, -1.224.000 per 6 mura).
DESELECT_POINT_BB = (1830, 65)  # barra oro in alto a destra, doppio tap per chiudere pannelli/selezioni


def _find_text_center(frame, region, needle):
    """Identico a _find_text_center() del villaggio primario: cerca
    `needle` (case-insensitive) nel testo OCR di una regione e ritorna il
    centro della prima occorrenza in coordinate assolute, o None."""
    l, t, w, h = region["left"], region["top"], region["width"], region["height"]
    crop = frame[t:t + h, l:l + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    data = pytesseract.image_to_data(mask, config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT)
    for i, word in enumerate(data["text"]):
        if needle.lower() in word.lower():
            cx = l + data["left"][i] + data["width"][i] // 2
            cy = t + data["top"][i] + data["height"][i] // 2
            return (cx, cy)
    return None


# v0.21 (2026-08-10): stesso fix del bot del villaggio primario (v3.14) -
# il dialog nativo di Clash of Clans "C'e' nessuno? La connessione e' stata
# interrotta per inattivita'" e' stato osservato dal vivo oggi (villaggio
# primario, ma e' un dialog di gioco generico, non specifico di un
# villaggio - può comparire anche qui). Rilevato via OCR, NESSUN tap
# automatico sul pulsante "RICARICA GIOCO" (testato dal vivo sul primario:
# ha chiuso l'intero processo HD-Player.exe invece di ricaricare la
# partita - rischio peggiore del problema). Se rilevato, manda una foto e
# solleva un errore vero invece di procedere alla cieca con deploy_wave().
RECONNECT_DIALOG_REGION = {"left": 560, "top": 400, "width": 850, "height": 280}


def _check_reconnect_dialog():
    frame = adb_screenshot()
    if _find_text_center(frame, RECONNECT_DIALOG_REGION, "interrotta") is None:
        return False
    debug_path = "debug_reconnect_dialog.png"
    cv2.imwrite(debug_path, frame)
    send_telegram_photo(
        debug_path,
        "🛑 Il gioco mostra 'Connessione interrotta per inattività' - non tocco da solo "
        "RICARICA GIOCO (rischia di chiudere l'emulatore, verificato dal vivo sul primario). "
        "Ricarica il gioco a mano, poi riavvia il bot.",
    )
    return True


def _find_action_bar_buttons(frame):
    """Identico a _find_action_bar_buttons() del villaggio primario:
    trova i pulsanti (rettangoli bianchi arrotondati) nella barra azioni in
    basso, li ritorna come lista di centri (x, y) da sinistra a destra."""
    l, t, w, h = WALL_ACTION_BAR_REGION["left"], WALL_ACTION_BAR_REGION["top"], WALL_ACTION_BAR_REGION["width"], WALL_ACTION_BAR_REGION["height"]
    crop = frame[t:t + h, l:l + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw > 100 and bh > 100:
            boxes.append((l + x + bw // 2, t + y + bh // 2))
    boxes.sort(key=lambda p: p[0])
    return boxes


def _find_action_bar_buttons_retry(min_count, attempts=3, delay=0.8, debug_name=None):
    """Identico a _find_action_bar_buttons_retry() del villaggio primario."""
    buttons = []
    frame = None
    for attempt in range(attempts):
        frame = adb_screenshot()
        buttons = _find_action_bar_buttons(frame)
        if len(buttons) >= min_count:
            return buttons
        if attempt < attempts - 1:
            time.sleep(delay)
    if debug_name and frame is not None:
        l, t = WALL_ACTION_BAR_REGION["left"], WALL_ACTION_BAR_REGION["top"]
        w, h = WALL_ACTION_BAR_REGION["width"], WALL_ACTION_BAR_REGION["height"]
        cv2.imwrite(f"debug_action_bar_{debug_name}.png", frame[t:t + h, l:l + w])
    return buttons


def _wall_cost_is_red(frame, button_center):
    """Identico a _wall_cost_is_red() del villaggio primario: True se il
    costo mostrato sopra il pulsante 'Migliora' (oro) è rosso - il gioco lo
    fa quando l'oro disponibile non basta più.

    Ricalibrato dal vivo il 2026-08-08 (bug reale trovato durante un test):
    l'offset/dimensione ereditati dal villaggio primario catturavano solo
    il bordo inferiore del numero di costo, non il numero stesso - con un
    costo a 7 cifre (es. "4 080 000") il crop cadeva quasi tutto su sfondo
    chiaro invece che sul testo, diluendo il conteggio di pixel rossi sotto
    soglia e facendo tornare sempre "non rosso" anche quando lo era
    visibilmente. Risultato pratico osservato: il batch è arrivato a 34
    mura (4.080.000 richiesti) con solo 3.976.404 disponibili, senza mai
    fermarsi prima. Nessuna spesa avvenuta (il controllo successivo sul
    dialog di conferma ha comunque rifiutato di dichiarare successo), ma
    va corretto per evitare di sprecare interi giri. Nuovo
    offset/dimensione verificati su due screenshot reali (uno col costo in
    rosso, uno in bianco) prima di essere adottati."""
    cx, cy = button_center
    ox, oy = WALL_COST_LABEL_OFFSET
    hw, hh = WALL_COST_LABEL_SIZE
    x, y = cx + ox, cy + oy
    crop = frame[y - hh:y + hh, x - hw:x + hw]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    bright_mask = cv2.inRange(hsv, (0, 0, 150), (180, 255, 255))
    pixels = crop[bright_mask > 0]
    if len(pixels) < 20:
        return False
    b = pixels[:, 0].mean()
    g = pixels[:, 1].mean()
    r = pixels[:, 2].mean()
    return (r - g) > 20


def deselect_all_bb():
    """Chiude qualunque pannello/selezione aperta toccando due volte la
    barra dell'oro in alto (stesso trucco del villaggio primario, stessa
    affidabilità altalenante già documentata lì - "a volte funziona, a
    volte apre solo il tooltip Max" - accettato come rischio noto, non
    pericoloso: non spende nulla da solo)."""
    adb_tap(*DESELECT_POINT_BB)
    time.sleep(0.6)
    adb_tap(*DESELECT_POINT_BB)
    time.sleep(1.0)


def _close_wall_panel():
    """Chiude qualunque pannello/tendina mura aperta toccando una zona
    rocciosa vuota fuori dalla base (WALL_EMPTY_MAP_POINT) - più affidabile
    di deselect_all_bb() per uso ripetuto (vedi commento sulla costante)."""
    adb_tap(*WALL_EMPTY_MAP_POINT)
    time.sleep(1.2)


def _find_wall_entries(frame):
    """Trova tutte le voci 'Muro' visibili nella tendina (regione
    WALL_DROPDOWN_REGION) nella schermata corrente. Per ognuna ritorna il
    centro (x, y) e una "firma" testuale - il suffisso "xN" che compare
    subito alla sua destra sulla stessa riga (es. "x36", "x130"), o ""
    se non c'è suffisso (un solo muro rimasto a quel livello).

    La firma NON dipende dalla posizione di scroll (a differenza di "y") -
    permette di ritrovare la STESSA voce fisica in modo affidabile anche
    dopo aver richiuso e riaperto la tendina, senza dover contare gli
    swipe per tornare in un punto preciso. Necessario perché verificato
    dal vivo l'8/8/2026 che lo scroll NON è riproducibile con precisione
    sufficiente: ripetere lo stesso numero di swipe da una tendina appena
    riaperta può arrivare anche una riga intera più in là o più in qua
    (rischio concreto quando più voci 'Muro' sono adiacenti, come visto
    dal vivo lo stesso giorno - 3 voci a distanza di una sola riga l'una
    dall'altra), causando selezioni sbagliate e comportamento erratico."""
    l, t, w, h = WALL_DROPDOWN_REGION["left"], WALL_DROPDOWN_REGION["top"], WALL_DROPDOWN_REGION["width"], WALL_DROPDOWN_REGION["height"]
    crop = frame[t:t + h, l:l + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    data = pytesseract.image_to_data(mask, config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT)
    n = len(data["text"])
    results = []
    for i in range(n):
        word = data["text"][i]
        if "muro" not in word.lower():
            continue
        cx = l + data["left"][i] + data["width"][i] // 2
        cy = t + data["top"][i] + data["height"][i] // 2
        my = data["top"][i] + data["height"][i] // 2
        mx_right = data["left"][i] + data["width"][i]
        suffix = ""
        for j in range(i + 1, min(i + 3, n)):
            w2 = data["text"][j].strip()
            if not w2:
                continue
            y2c = data["top"][j] + data["height"][j] // 2
            x2 = data["left"][j]
            if abs(y2c - my) <= 15 and 0 <= x2 - mx_right <= 60 and re.match(r"^[xX]\d{1,4}$", w2):
                suffix = w2.lower()
            break
        results.append({"x": cx, "y": cy, "suffix": suffix})
    return results


def _scan_all_wall_entries():
    """Scorre l'INTERA tendina 'Miglioramenti' dalla cima fino in fondo
    (WALL_LIST_MAX_SCROLL_STEPS swipe fissi), raccogliendo OGNI voce
    'Muro' distinta trovata (per firma - vedi _find_wall_entries), sparse
    in punti diversi della lista e non ordinate per costo/livello (vedi
    commento generale sopra try_wall_upgrade). Assume che la tendina sia
    già aperta e in cima.

    Deduplica per firma (non per posizione - lo swipe usato è piccolo
    apposta per non saltare mai una voce, quindi la stessa voce fisica
    ricompare quasi sempre in più schermate consecutive che si
    sovrappongono): la prima comparsa di ogni firma viene tenuta, le altre
    scartate. Il caso "senza suffisso" (un solo muro rimasto a quel
    livello) non si deduplica altrettanto bene - ogni comparsa è trattata
    come potenzialmente distinta - ma nell'account attuale esiste sempre
    e solo una voce del genere per volta, quindi comporta solo qualche
    rilettura extra innocua, non una scelta sbagliata.

    Ritorna una lista di dict {"x": int, "y": int, "suffix": str} (x/y
    solo informativi, per il conteggio - la voce viene sempre ritrovata
    davvero via _find_wall_by_signature prima di ogni interazione)."""
    entries = []
    seen_signatures = set()
    for step in range(WALL_LIST_MAX_SCROLL_STEPS):
        frame = adb_screenshot()
        for e in _find_wall_entries(frame):
            key = e["suffix"] if e["suffix"] else f"_senza_suffisso_{step}"
            if key in seen_signatures:
                continue
            seen_signatures.add(key)
            entries.append(e)
        (x1, y1), (x2, y2) = WALL_DROPDOWN_SCROLL
        adb_swipe(x1, y1, x2, y2, duration_ms=600)
        time.sleep(1.0)
    return entries


def _find_wall_by_signature(signature, max_attempts=WALL_MAX_SCROLL_ATTEMPTS):
    """Cerca una voce 'Muro' specifica (identificata dalla sua firma, es.
    "x36", o "" per l'unico muro senza suffisso) scorrendo dall'alto -
    tendina già aperta e in cima. A differenza di un riposizionamento
    "alla cieca" per conteggio di swipe, cerca sempre il contenuto vero
    via OCR fresco ad ogni tentativo: non risente della deriva dello
    scroll (vedi _find_wall_entries). Ritorna il centro (x, y) della voce
    trovata, o None se non trovata entro `max_attempts` scroll."""
    for _ in range(max_attempts):
        frame = adb_screenshot()
        for e in _find_wall_entries(frame):
            if e["suffix"] == signature:
                return (e["x"], e["y"])
        (x1, y1), (x2, y2) = WALL_DROPDOWN_SCROLL
        adb_swipe(x1, y1, x2, y2, duration_ms=600)
        time.sleep(1.0)
    return None


def _read_wall_level(frame):
    """Legge il livello dal titolo grande che compare sopra i pulsanti
    dopo aver selezionato una voce ('Muro (liv. N)', font grande e pulito,
    niente separatori delle migliaia - molto più affidabile del testo dei
    costi, che soffre del bug delle "cifre fantasma" già documentato altrove
    in questo file). Calibrato dal vivo il 2026-08-08 su 4 livelli reali
    diversi (3, 4, 5, 6): soglia 195 + upscale 3x + psm 6 ha letto tutti e
    4 correttamente (altre combinazioni soglia/scala/psm provate fallivano
    su almeno un caso). Ritorna il livello (int) o None se non riesce a
    leggerlo o se il numero letto è fuori da un range plausibile (vedi
    WALL_LEVEL_MAX_PLAUSIBLE) - scoperto dal vivo il 2026-08-08 che a volte
    l'etichetta fluttuante con lo stesso testo mostrata sulla mappa accanto
    al muro selezionato (posizione variabile, dipende da dove si trova
    fisicamente quel muro) finiva anch'essa nel crop e confondeva l'OCR,
    producendo letture chiaramente sbagliate (es. "23", "43") - uno scarto
    per range implausibile è un filtro semplice e sicuro (nel dubbio,
    tratta come illeggibile e salta quella voce, non sceglierla mai)."""
    l, t = WALL_LEVEL_TITLE_REGION["left"], WALL_LEVEL_TITLE_REGION["top"]
    w, h = WALL_LEVEL_TITLE_REGION["width"], WALL_LEVEL_TITLE_REGION["height"]
    crop = frame[t:t + h, l:l + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 195, 255, cv2.THRESH_BINARY)
    big = cv2.resize(mask, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    text = pytesseract.image_to_string(big, config="--oem 3 --psm 6").strip()
    m = re.search(r"[il1]iv[.:;,']*\s*[.:;,']*\s*(\d{1,2})", text, re.IGNORECASE)
    if not m:
        return None
    level = int(m.group(1))
    if level < 1 or level > WALL_LEVEL_MAX_PLAUSIBLE:
        return None
    return level


def try_wall_upgrade():
    """Un giro di upgrade mura nel Villaggio Costruttori: scansiona TUTTA
    la tendina 'Miglioramenti', legge il livello reale di ogni voce 'Muro'
    trovata (vedi commento generale sopra sul perché non basta più "la
    prima trovata"), seleziona quella al livello più basso, poi aggiunge
    mura al batch una alla volta ("Aggiungi mura +1", mai +10 - stessa
    scelta esplicita del villaggio primario) finché il costo in oro non
    diventa rosso (fondi insufficienti), infine conferma il pagamento.

    A differenza di try_wall_upgrade() nel villaggio primario: valuta
    sempre e solo oro (nessuna scelta tra due valute, l'Anello da mura non
    viene mai usato), nessun controllo costruttore libero (upgrade sempre
    istantaneo). Ritorna True se ha confermato un upgrade, False se ha
    saltato per qualunque motivo (nessuna eccezione sollevata: l'obiettivo
    è che un fallimento qui non comprometta il ciclo di attacco normale).

    Controllo di sicurezza aggiunto il 2026-08-08 (richiesto esplicitamente
    dall'utente dopo aver visto dal vivo un giro precedente comportarsi in
    modo erratico): verifica che il gioco sia davvero sul Villaggio
    Costruttori PRIMA di aprire la tendina e di nuovo dopo aver scelto la
    voce da migliorare - se per qualunque motivo il villaggio risulta
    cambiato nel frattempo (es. un tap finito fuori bersaglio ha toccato la
    barca), il giro viene interrotto subito con un avviso Telegram invece
    di continuare a operare alla cieca sullo schermo sbagliato.
    """
    if detect_village_type() != "costruttore":
        print("[MURA] Non risulto sul Villaggio Costruttori, salto per sicurezza (nessuna azione).")
        send_telegram("⚠️ Villaggio Costruttori: upgrade mura saltato, il gioco non risultava sul villaggio giusto prima di iniziare.")
        return False

    print("[MURA] Apro la tendina e scansiono tutte le voci 'Muro'...")
    adb_tap(*BUILDER_BADGE_POINT_BB)
    time.sleep(1.5)

    entries = _scan_all_wall_entries()
    if not entries:
        print("[MURA] Voce 'Muro' non trovata al primo giro, riprovo riaprendo la tendina...")
        adb_tap(*BUILDER_BADGE_POINT_BB)
        time.sleep(1.0)
        adb_tap(*BUILDER_BADGE_POINT_BB)
        time.sleep(1.5)
        entries = _scan_all_wall_entries()
    if not entries:
        print("[MURA] Non ho trovato nessuna voce 'Muro' nella tendina, salto.")
        _close_wall_panel()
        return False

    print(f"[MURA] Trovate {len(entries)} voci 'Muro' distinte, leggo il livello di ognuna...")
    best = None  # (level, signature)
    for i, entry in enumerate(entries):
        signature = entry["suffix"]
        label = signature if signature else "senza suffisso"

        if not signature:
            # L'unico muro rimasto a un dato livello (nessun suffisso "xN",
            # quindi nessun gruppo da cui aggiungerne altri) non si può
            # comprare con questo flusso: scoperto dal vivo il 2026-08-08
            # che "Migliora ancora" su una voce del genere non apre affatto
            # la modalità batch (il gioco probabilmente non ha nulla da
            # "aggiungere" con un solo muro disponibile) - il pannello resta
            # identico e i controlli sotto abortirebbero comunque senza
            # spendere nulla, ma inutilmente dopo aver già navigato fin lì.
            # Si scarta subito, senza nemmeno leggerne il livello: se
            # capita di essere davvero il livello più basso in assoluto,
            # quel muro resterà indietro finché non si aggrega a un gruppo
            # più ampio (es. un altro muro portato allo stesso livello).
            print(f"[MURA] Voce {i + 1}/{len(entries)} ('{label}'): muro singolo, il batch 'Migliora ancora' non funziona su queste voci - la salto.")
            continue

        _close_wall_panel()
        adb_tap(*BUILDER_BADGE_POINT_BB)
        time.sleep(1.5)
        found = _find_wall_by_signature(signature)
        if not found:
            print(f"[MURA] Voce {i + 1}/{len(entries)} ('{label}'): non più trovata, la ignoro.")
            continue

        adb_tap(*found)
        time.sleep(1.5)
        # Selezionare una voce non chiude la tendina (stesso bug UI di
        # sempre): ritoccare il badge la chiude senza deselezionare, cosi'
        # il titolo "Muro (liv. N)" resta visibile e leggibile.
        adb_tap(*BUILDER_BADGE_POINT_BB)
        time.sleep(1.5)
        frame = adb_screenshot()
        level = _read_wall_level(frame)
        if level is None:
            print(f"[MURA] Voce {i + 1}/{len(entries)} ('{label}'): livello illeggibile, la ignoro.")
            continue
        print(f"[MURA] Voce {i + 1}/{len(entries)} ('{label}'): livello {level}.")
        if best is None or level < best[0]:
            best = (level, signature)

    _close_wall_panel()

    if best is None:
        print("[MURA] Non sono riuscito a leggere il livello di nessuna voce 'Muro', salto.")
        return False

    if detect_village_type() != "costruttore":
        print("[MURA] Non risulto più sul Villaggio Costruttori dopo la scansione, salto per sicurezza.")
        send_telegram("⚠️ Villaggio Costruttori: upgrade mura interrotto, il villaggio è cambiato durante la scansione.")
        return False

    best_level, best_signature = best
    print(f"[MURA] Livello più basso trovato: {best_level}. Procedo con l'upgrade.")

    adb_tap(*BUILDER_BADGE_POINT_BB)
    time.sleep(1.5)
    found = _find_wall_by_signature(best_signature)
    if not found:
        print("[MURA] La voce scelta non è più disponibile (probabilmente cambiata nel frattempo), salto.")
        _close_wall_panel()
        return False

    adb_tap(*found)
    time.sleep(1.5)

    # Selezionare una voce non chiude la tendina (stesso bug UI del
    # villaggio primario): ritoccare il badge la chiude senza deselezionare
    # il muro (stesso "toggle" già usato per aprirla).
    adb_tap(*BUILDER_BADGE_POINT_BB)
    time.sleep(1.5)

    # Selezione singola: di solito 4 pulsanti (Info | Migliora ancora |
    # Migliora oro | Migliora anello) o 5 se compare anche "Selez. Riga" -
    # "Migliora ancora" è il terzultimo in entrambi i casi (stessa
    # posizione relativa verificata dal vivo il 2026-08-04). ATTENZIONE:
    # scoperto dal vivo il 2026-08-08 che una voce puo' offrire ANCHE il
    # pagamento in elisir (6 pulsanti: Info | Selez.Riga | Migliora ancora
    # | Migliora oro | Migliora elisir | Migliora anello) - in quel caso
    # "terzultimo" NON è più "Migliora ancora" ma "Migliora oro" (bug
    # latente non ancora risolto, di fatto innocuo: se capita, il tap
    # sbagliato non apre la modalità batch attesa, i controlli sotto non
    # trovano la barra a 5 pulsanti e il giro viene saltato senza spendere
    # nulla - vedi anche il commento generale in cima sul perché questo
    # scenario è raro con la scelta "livello più basso").
    buttons = _find_action_bar_buttons_retry(4, debug_name="bb_selezione")
    if len(buttons) < 4:
        print(f"[MURA] Barra pulsanti inattesa ({len(buttons)} invece di 4-6), salto.")
        deselect_all_bb()
        return False

    ancora_center = buttons[-3]
    adb_tap(*ancora_center)
    time.sleep(1.2)

    # Modalità batch dopo "Migliora ancora": Togli mura -1 | Aggiungi +10 |
    # Aggiungi +1 | Migliora oro | (Migliora elisir, se presente) | Migliora
    # anello - "Migliora oro" è sempre il primo pulsante di pagamento,
    # terza posizione da sinistra (indice 3), qualunque sia il numero
    # totale di pulsanti (verificato dal vivo anche sulla voce a 6
    # pulsanti del 2026-08-08).
    buttons = _find_action_bar_buttons_retry(5, debug_name="bb_batch")
    if len(buttons) < 5:
        print(f"[MURA] Barra pulsanti batch inattesa ({len(buttons)} invece di 5-6), ritento 'Migliora ancora'...")
        adb_tap(*ancora_center)
        time.sleep(1.5)
        buttons = _find_action_bar_buttons_retry(5, debug_name="bb_batch")
    if len(buttons) < 5:
        print(f"[MURA] Barra pulsanti batch ancora inattesa ({len(buttons)} invece di 5-6), salto.")
        deselect_all_bb()
        return False

    add_one_point = buttons[2]
    remove_one_point = buttons[0]
    pay_point = buttons[3]  # sempre oro, mai l'Anello da mura o l'elisir (vedi commento in cima)

    frame = adb_screenshot()
    if _wall_cost_is_red(frame, pay_point):
        print("[MURA] Oro insufficiente per anche solo il primo muro, non confermo nulla.")
        deselect_all_bb()
        return False

    target_count = 1
    for _ in range(WALL_MAX_ADD_TAPS):
        adb_tap(*add_one_point)
        time.sleep(0.9)
        frame = adb_screenshot()
        if _wall_cost_is_red(frame, pay_point):
            adb_tap(*remove_one_point)
            time.sleep(0.9)
            break
        target_count += 1
    else:
        print(f"[MURA] Raggiunto il tetto di sicurezza di {WALL_MAX_ADD_TAPS} mura senza mai vedere il costo in rosso.")

    print(f"[MURA] Punto a {target_count} mura di livello {best_level}, pago in oro.")

    buttons = _find_action_bar_buttons_retry(5, debug_name="bb_dopo_aggiungi")
    if len(buttons) < 5:
        print("[MURA] Pulsanti spariti dopo gli 'Aggiungi mura', non confermo nulla per sicurezza.")
        deselect_all_bb()
        return False

    pay_point = buttons[3]
    adb_tap(*pay_point)
    time.sleep(1.5)

    # Dialog di conferma finale ("Migliora le mura" / "Vuoi davvero
    # migliorare le mura selezionate per N Oro del costruttore?",
    # Annulla/OK) - senza questo tap il flusso si blocca qui, nessuna
    # spesa avviene. Verificato dal vivo il 2026-08-04 (posizione fissa).
    adb_tap(*GENERIC_DIALOG_CONFIRM_POINT)
    time.sleep(1.5)

    # Verifica che il dialog si sia davvero chiuso, invece di fidarsi
    # ciecamente del tap: scoperto dal vivo il 2026-08-04 che un punto di
    # conferma sbagliato (copiato per errore dal dialog del muro singolo,
    # diverso da questo) fa fallire il pagamento IN SILENZIO - il dialog
    # resta aperto ma il codice, senza questo controllo, riporterebbe
    # comunque "confermato" (falso positivo, oro invariato). Un pixel al
    # centro del box del dialog è chiaro/crema quando è aperto, molto più
    # scuro quando è chiuso (schermo di gioco/pannello sotto) - calibrato
    # sul vivo: aperto ~688 (somma BGR), chiuso ~170-433 a seconda del
    # pannello sotto, soglia 500 sta comodamente in mezzo.
    frame = adb_screenshot()
    b, g, r = (int(v) for v in frame[500, 960])
    if (b + g + r) > 500:
        print("[MURA] Il dialog di conferma sembra ancora aperto dopo il tap: il pagamento potrebbe non essere andato a segno, non mi fido del successo.")
        send_telegram("⚠️ Villaggio Costruttori: upgrade mura forse fallito (dialog di conferma ancora aperto). Controllo manuale consigliato.")
        deselect_all_bb()
        return False

    print(f"[MURA] Confermato upgrade di {target_count} mura di livello {best_level}, pagato in oro.")
    send_telegram(f"🧱 Villaggio Costruttori: upgrade di {target_count} mura di livello {best_level} (oro).")

    deselect_all_bb()
    time.sleep(1.0)
    return True


def collect_elixir_cart():
    """Svuota il carretto elisir (ricompense dalle difese subite, si
    accumulano fino a un cap di 1.600.000 - non è collegato al bottino dei
    propri attacchi). Va chiamata dalla home del Villaggio Costruttori.
    Sicura da chiamare anche se non ci sono nuove ricompense: "Prendi"
    resta cliccabile senza alcun effetto collaterale in quel caso.
    """
    print("[CARRETTO] Cerco il carretto elisir (pan camera verso l'alto)...")
    adb_swipe(CART_SWIPE_UP[0][0], CART_SWIPE_UP[0][1], CART_SWIPE_UP[1][0], CART_SWIPE_UP[1][1])
    time.sleep(1.0)
    adb_tap(*ELIXIR_CART_POINT)
    time.sleep(1.5)
    print("[CARRETTO] Premo 'Prendi'...")
    adb_tap(*CART_TAKE_BUTTON)
    time.sleep(1.5)
    adb_tap(*CART_CLOSE_BUTTON)
    time.sleep(1.0)


def deploy_wave():
    """Un passaggio di schieramento completo (usato identico per raid 1 e
    raid 2): porta la camera in posizione fissa, schiera ogni unità della
    barra su uno dei due punti calibrati, poi ri-tocca le icone per
    attivare le abilità.
    """
    print("[DEPLOY] Porto la camera in posizione fissa...")
    adb_swipe(CAMERA_SWIPE_START[0], CAMERA_SWIPE_START[1], CAMERA_SWIPE_END[0], CAMERA_SWIPE_END[1], CAMERA_SWIPE_DURATION_MS)
    time.sleep(0.7)

    print("[DEPLOY] Schiero le unità...")
    deploy_cycle = itertools.cycle(DEPLOY_POINTS)
    for slot_x in UNIT_SLOTS_X:
        adb_tap(slot_x, UNIT_BAR_Y)
        time.sleep(random.uniform(0.08, 0.14))
        dx, dy = next(deploy_cycle)
        adb_tap(dx, dy)
        time.sleep(random.uniform(*INTER_TAP_DELAY_RANGE))

    time.sleep(ABILITY_RETAP_DELAY)

    print("[DEPLOY] Attivo le abilità (ri-tocco ogni icona)...")
    for slot_x in UNIT_SLOTS_X:
        adb_tap(slot_x, UNIT_BAR_Y)
        time.sleep(random.uniform(0.10, 0.16))


def _read_top_banner_state(frame=None):
    """Legge la scritta in alto ("La battaglia inizia/termina tra:") via
    OCR. Ritorna "inizia" (il raid successivo è pronto, si può schierare
    subito), "termina" (battaglia in corso) o None (scritta non letta -
    es. schermata di risultati, dove questo banner non c'è)."""
    if frame is None:
        frame = adb_screenshot()
    l, t = TOP_BANNER_REGION["left"], TOP_BANNER_REGION["top"]
    w, h = TOP_BANNER_REGION["width"], TOP_BANNER_REGION["height"]
    crop = frame[t:t + h, l:l + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    text = pytesseract.image_to_string(gray, config="--psm 6").lower()
    if "inizia" in text:
        return "inizia"
    if "termina" in text:
        return "termina"
    return None


def _is_results_screen(frame=None):
    """True se siamo sulla schermata finale "Truppe utilizzate /
    Ricompense / Torna al villaggio" (fine dei due raid)."""
    if frame is None:
        frame = adb_screenshot()
    x, y = RESULTS_SCREEN_CHECK_POINT
    b, g, r = (int(v) for v in frame[y, x])
    return (r + g + b) < RESULTS_SCREEN_MAX_BRIGHTNESS


def wait_for_next_screen(max_wait=BATTLE_WAIT_SECONDS, poll_interval=BATTLE_POLL_INTERVAL):
    """Aspetta che il raid corrente finisca, controllando attivamente lo
    schermo invece di dormire un tempo fisso. Ritorna:
    - "next_raid" appena legge "La battaglia inizia tra:" (il raid
      successivo esiste - ATTENZIONE (v0.20): questa è ancora una
      schermata di anteprima/scouting, NON si può schierare subito
      nonostante quanto assunto fino alla v0.19 - il chiamante deve
      aspettare che il banner diventi "termina" prima di schierare, vedi
      run_double_raid());
    - "results" appena rileva la schermata finale (niente secondo raid, il
      primo non ha raggiunto il 100%);
    - "timeout" se `max_wait` scade prima (rete di sicurezza).
    """
    started = time.monotonic()
    while time.monotonic() - started < max_wait:
        frame = adb_screenshot()
        if _is_results_screen(frame):
            print("[WAIT] Schermata dei risultati rilevata.")
            return "results"
        if _read_top_banner_state(frame) == "inizia":
            print("[WAIT] 'La battaglia inizia tra' rilevato, il prossimo raid è pronto.")
            return "next_raid"
        time.sleep(poll_interval)
    print(f"[WAIT] Tetto massimo di {max_wait:.0f}s raggiunto, procedo comunque.")
    return "timeout"


def run_double_raid():
    """Un ciclo completo: avvia l'attacco, schiera sul primo raid, aspetta
    (con controllo attivo) che finisca, ripete lo schieramento per il
    secondo raid se si è sbloccato, aspetta di nuovo, torna al villaggio.
    """
    # v0.17→v0.18: qui c'era un tap "di sicurezza" su STAR_BONUS_OK_BUTTON
    # per chiudere un eventuale popup "Bonus stella!" rimasto aperto dal
    # ciclo precedente. Rimosso del tutto (non reso condizionale su
    # is_home_screen() - vedi perché più sotto, stesso motivo per il tap
    # gemello a fine ciclo): _ensure_home_or_recover() a fine ciclo garantisce
    # già di ripartire da una home pulita, quindi non serve più.
    print("[ATTACK] Tocco 'Attacco!'...")
    adb_tap(*ATTACK_BUTTON)
    time.sleep(1.2)

    # v0.21: se il tap su "Attacco!" non ha aperto nulla (siamo ancora sulla
    # home), non procedere alla cieca con Cerca!/deploy_wave() - prima
    # controlla se il vero motivo e' il dialog "connessione interrotta"
    # (vedi _check_reconnect_dialog).
    if is_home_screen():
        if _check_reconnect_dialog():
            raise RuntimeError("Dialog 'connessione interrotta per inattività' rilevato: serve intervento manuale, non riprovo alla cieca.")
        print("[ATTACK] 'Attacco!' non sembra essersi aperto (popup imprevisto?), riprovo...")
        adb_tap(*ATTACK_BUTTON)
        time.sleep(1.5)
        if is_home_screen():
            if _check_reconnect_dialog():
                raise RuntimeError("Dialog 'connessione interrotta per inattività' rilevato: serve intervento manuale, non riprovo alla cieca.")
            debug_path = "debug_attack_stuck.png"
            cv2.imwrite(debug_path, adb_screenshot())
            send_telegram_photo(debug_path, "⚠️ Non riesco ad aprire la schermata di attacco (forse un popup blocca il villaggio). Salto un ciclo - ecco cosa vedo io in questo momento.")
            raise RuntimeError("'Attacco!' non si apre dopo due tentativi.")

    print("[ATTACK] Tocco 'Cerca!'...")
    adb_tap(*SEARCH_BUTTON)
    time.sleep(1.5)

    print("[ATTACK] Confermo l'eventuale popup 'Disposizione difensiva ostruita'...")
    adb_tap(*OBSTRUCTED_LAYOUT_OK_POINT)
    time.sleep(WAIT_BEFORE_DEPLOY)

    print("[RAID 1/2] Schieramento...")
    deploy_wave()

    print("[RAID 1/2] Aspetto la fine della battaglia (controllo attivo)...")
    outcome = wait_for_next_screen()

    if outcome == "results":
        print("[RAID 2/2] Niente secondo raid (il primo non ha raggiunto il 100%).")
    else:
        # v0.19 (primo tentativo, insufficiente): bug segnalato dall'utente -
        # a volte, solo sul secondo raid, la PRIMA unità della barra (spesso
        # una strega) non veniva schierata. Ipotesi iniziale: una breve
        # attesa fissa (1.5s) per lasciare "assestare" lo schermo. Smentita
        # dal vivo poche battaglie dopo: un intero raid ha schierato quasi
        # zero truppe, non solo la prima.
        #
        # v0.20, causa vera trovata dal vivo (confronto screenshot): "la
        # battaglia INIZIA tra: Ns" (rilevato da wait_for_next_screen come
        # segnale "prossimo raid pronto") è ancora una schermata di ANTEPRIMA
        # dell'avversario - bottone "Termina battaglia", camera larga in
        # stile scouting, NESSUNA truppa/pannello "Danno complessivo" - non
        # la vera schermata di battaglia (quella ha "Resa" in basso a
        # sinistra, la camera vicina al bordo villaggio dopo il pan di
        # deploy_wave(), e mostra "la battaglia TERMINA tra"). Il countdown
        # "inizia" osservato dal vivo è arrivato fino a 55s ancora da
        # scadere, molto più lungo del margine che qualunque attesa fissa
        # breve potrebbe coprire - il vecchio commento su questa funzione
        # ("si può schierare subito, anche durante quel countdown") era
        # semplicemente sbagliato per questa fase. Fix: aspettare
        # attivamente (stesso meccanismo OCR di wait_for_next_screen, non
        # un'attesa a tempo fisso) che il banner passi a "termina" - cioè
        # che la battaglia vera sia davvero iniziata - prima di schierare.
        print("[RAID 2/2] Secondo raid pronto, aspetto che la battaglia vera cominci...")
        started = time.monotonic()
        while time.monotonic() - started < RAID2_PREVIEW_MAX_WAIT:
            if _read_top_banner_state() == "termina":
                break
            time.sleep(BATTLE_POLL_INTERVAL)
        else:
            print(f"[RAID 2/2] Tetto massimo di {RAID2_PREVIEW_MAX_WAIT:.0f}s raggiunto, schiero comunque.")
        print("[RAID 2/2] Schiero...")
        deploy_wave()
        print("[RAID 2/2] Aspetto la fine della battaglia (controllo attivo)...")
        wait_for_next_screen()

    print("[ATTACK] Torno al villaggio...")
    adb_tap(*RETURN_HOME_BUTTON)
    time.sleep(1.6)

    # v0.17: bug vero trovato dal vivo il 2026-08-09, analizzando ogni tap
    # con screenshot di debug dopo ognuno (richiesto esplicitamente
    # dall'utente dopo che il bug si ripresentava nonostante v0.16). Qui
    # c'era un tap "di sicurezza" su STAR_BONUS_OK_BUTTON (960, 838) per
    # chiudere un eventuale popup "Bonus stella!", eseguito sempre "a vuoto
    # se non serve" - ma quel punto è una coordinata sulla MAPPA di gioco,
    # non un elemento di UI fisso: se in quel momento un muro (o altro
    # edificio) si trova lì sotto (dipende da dove sta la camera, mai
    # garantito identico - stesso problema di fondo già documentato per la
    # barca), il tap apre il suo pannello invece di non fare nulla.
    # Osservato dal vivo: il primo tap ha aperto il pannello "Muro (liv. 8)",
    # il secondo tap (stesso punto, sul pannello ora aperto) è caduto sul
    # pulsante "Migliora" (oro), aprendo un vero dialog di conferma spesa
    # "Portare al livello 9? 640.000 Oro" - a un tap di distanza da una
    # spesa reale non voluta (nessuna spesa avvenuta, chiuso in tempo).
    #
    # v0.18, correzione della correzione: il primo tentativo di fix (tappare
    # solo se `not is_home_screen()`) NON ha risolto il problema - risolto
    # sulla carta ma smentito da un secondo test dal vivo identico subito
    # dopo il deploy, stesso identico dialog riaperto. Causa: is_home_screen()
    # stesso può dare un falso negativo per lo stesso motivo di fondo (il
    # pixel controllato può cadere fuori posto a seconda dello zoom/pan della
    # camera, già documentato altrove in questo file) - quindi la condizione
    # "tocca solo se NON risultiamo sulla home" può restare vera anche su una
    # home già pulita, facendo comunque scattare il tap rischioso. Un
    # controllo che può sbagliarsi non è una guardia affidabile per un tap
    # che può costare soldi veri. Fix definitivo: **tap rimosso del tutto**,
    # sia qui che a inizio ciclo - non è mai stato osservato dal vivo un
    # vero popup "Bonus stella!" bloccare qualcosa in tutti i test di oggi,
    # quindi il beneficio era comunque minimo. _ensure_home_or_recover() qui
    # sotto resta come unica rete di sicurezza, con un punto di recovery
    # scelto apposta fuori dall'area costruibile (RECOVERY_EMPTY_MAP_POINT) -
    # non una coordinata che può sovrapporsi a un edificio vero.
    if not _ensure_home_or_recover():
        raise RuntimeError(
            "Non risultiamo su una schermata home dopo il ciclo (popup imprevisto "
            "bloccato?) - vedi _ensure_home_or_recover()."
        )


COLLECT_ELIXIR_EVERY = 10  # ogni quanti cicli svuotare il carretto elisir
WALL_UPGRADE_EVERY = 20    # ogni quanti cicli tentare un upgrade mura


def main():
    parser = argparse.ArgumentParser(description="Bot Villaggio Costruttori - solo flusso di attacco")
    parser.add_argument(
        "--cycles", type=int, default=1,
        help="Quanti cicli di doppio raid eseguire (default 1, pensato per un primo test supervisionato). "
             "Usa 0 per un loop continuo (finché non lo fermi tu)."
    )
    args = parser.parse_args()

    print("[HOME] Attendo che il villaggio sia pronto...")
    home_ready = False
    for _ in range(15):
        if is_home_screen():
            home_ready = True
            break
        time.sleep(1.0)

    if home_ready:
        print("[VILLAGGIO] Controllo di essere sul Villaggio Costruttori...")
        if not switch_to_village("costruttore"):
            send_telegram(
                "⛔ Villaggio Costruttori: impossibile passare al villaggio giusto "
                "(tap sulla barca fallito, forse coordinate da ricalibrare). Mi fermo "
                "invece di attaccare alla cieca sul villaggio sbagliato."
            )
            return
    else:
        print("[VILLAGGIO] Non risultiamo su una schermata home dopo l'attesa, salto il controllo villaggio.")

    send_telegram(f"🏗️ Bot Villaggio Costruttori v{VERSION} avviato ({'continuo' if args.cycles == 0 else f'{args.cycles} cicli'}).")

    cycle = 0
    consecutive_errors = 0
    try:
        while args.cycles == 0 or cycle < args.cycles:
            cycle += 1
            print(f"\n[CICLO {cycle}{'' if args.cycles == 0 else f'/{args.cycles}'}]")
            try:
                run_double_raid()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                print(f"[ERRORE] Ciclo {cycle} fallito: {e}")
                send_telegram(f"⚠️ Villaggio Costruttori: errore nel ciclo {cycle}: {e}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    send_telegram(f"⛔ Villaggio Costruttori: {MAX_CONSECUTIVE_ERRORS} errori di fila, mi fermo.")
                    break
                continue

            # Raccolta elisir e upgrade mura non ad ogni ciclo (su richiesta
            # esplicita dell'utente, 2026-08-04): prima erano nel percorso
            # normale di run_double_raid() ad ogni singolo ciclo. Un
            # eventuale errore qui non conta come fallimento del ciclo
            # (l'attacco è comunque andato a buon fine) - loggato e
            # notificato a parte, senza incrementare consecutive_errors.
            if cycle % COLLECT_ELIXIR_EVERY == 0:
                try:
                    collect_elixir_cart()
                except Exception as e:
                    print(f"[ERRORE] Raccolta elisir fallita al ciclo {cycle}: {e}")
                    send_telegram(f"⚠️ Villaggio Costruttori: raccolta elisir fallita al ciclo {cycle}: {e}")

            if cycle % WALL_UPGRADE_EVERY == 0:
                try:
                    try_wall_upgrade()
                except Exception as e:
                    print(f"[ERRORE] Upgrade mura fallito al ciclo {cycle}: {e}")
                    send_telegram(f"⚠️ Villaggio Costruttori: upgrade mura fallito al ciclo {cycle}: {e}")
    except KeyboardInterrupt:
        print("\n[STOP] Interrotto manualmente.")

    send_telegram(f"🏁 Bot Villaggio Costruttori fermo dopo {cycle} cicli.")


if __name__ == "__main__":
    main()
