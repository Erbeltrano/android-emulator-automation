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
compare solo quando il prossimo raid è pronto (si può schierare subito,
anche durante quel countdown). Letta via OCR (`_read_top_banner_state()`)
al posto del pulsante rosso - vedi `wait_for_next_screen()`.

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

VERSION = "0.13"


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
STAR_BONUS_OK_BUTTON = (960, 838)   # OK sul popup extra "Bonus stella!" (se compare)

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
# quando il prossimo raid è pronto e si può schierare subito (verificato:
# durante "termina tra" - battaglia in corso - OCR legge "termina", mai
# "inizia"). Appena la si legge, si schiera subito, senza aspettare altro.
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
HOME_CHECK_POINT = (135, 1010)
HOME_CHECK_MIN_DIFF = 50
# v0.8 (2026-08-04): BOAT_TO_BUILDER_POINT era un tap diretto (badge fisso
# sull'acqua) - ma un nuovo badge dell'evento stagionale ("Scheda degli
# incarichi", icona con countdown "27g 12h", non presente al momento della
# calibrazione originale) si è aggiunto sopra quel punto esatto della UI,
# intercettando il tap prima che arrivasse alla barca sottostante:
# switch_to_village("costruttore") falliva sempre (2 tentativi, "Cambio
# fallito"), scoperto dal vivo. Stesso fix già usato per il tragitto di
# ritorno: pan della camera per liberare la barca, poi tap.
BOAT_TO_BUILDER_PAN = ((1300, 700), (1650, 260))
BOAT_TO_BUILDER_POINT = (830, 390)
BOAT_TO_PRIMARY_PAN = ((1400, 300), (700, 700))
BOAT_TO_PRIMARY_POINT = (1670, 730)  # ricalibrato 2026-08-04, vedi commento in BOT_COMPLETO_MAC.py
VILLAGE_CHECK_REGION = {"left": 600, "top": 0, "width": 700, "height": 15}
VILLAGE_CHECK_GB_THRESHOLD = 20


def _home_pixel_says_home():
    frame = adb_screenshot()
    x, y = HOME_CHECK_POINT
    b, g, r = frame[y, x]
    return (int(r) - int(b)) > HOME_CHECK_MIN_DIFF


def is_home_screen():
    """True se siamo su una schermata home (di uno dei due villaggi, non
    in ricerca/battaglia) - verificato dal vivo che funziona identico su
    entrambi (stesso pulsante "Attacco!" arancione in entrambi i casi)."""
    if not _home_pixel_says_home():
        return False
    time.sleep(0.4)
    return _home_pixel_says_home()


def detect_village_type(frame=None):
    if frame is None:
        frame = adb_screenshot()
    l, t = VILLAGE_CHECK_REGION["left"], VILLAGE_CHECK_REGION["top"]
    w, h = VILLAGE_CHECK_REGION["width"], VILLAGE_CHECK_REGION["height"]
    crop = frame[t:t + h, l:l + w].astype(np.int32)
    b_mean = crop[:, :, 0].mean()
    g_mean = crop[:, :, 1].mean()
    return "primario" if (g_mean - b_mean) > VILLAGE_CHECK_GB_THRESHOLD else "costruttore"


def switch_to_village(target, max_attempts=2):
    for attempt in range(max_attempts):
        current = detect_village_type()
        if current == target:
            if attempt > 0:
                print(f"[VILLAGGIO] Ora siamo su '{target}'.")
            return True

        print(f"[VILLAGGIO] Siamo su '{current}', serve '{target}': tocco la barca...")
        if target == "costruttore":
            adb_swipe(BOAT_TO_BUILDER_PAN[0][0], BOAT_TO_BUILDER_PAN[0][1],
                      BOAT_TO_BUILDER_PAN[1][0], BOAT_TO_BUILDER_PAN[1][1])
            time.sleep(0.8)
            adb_tap(*BOAT_TO_BUILDER_POINT)
        else:
            adb_swipe(BOAT_TO_PRIMARY_PAN[0][0], BOAT_TO_PRIMARY_PAN[0][1],
                      BOAT_TO_PRIMARY_PAN[1][0], BOAT_TO_PRIMARY_PAN[1][1])
            time.sleep(0.8)
            adb_tap(*BOAT_TO_PRIMARY_POINT)
        time.sleep(4.0)

    # v0.9: stesso fix di BOT_COMPLETO_MAC.py - il controllo veniva fatto
    # solo PRIMA di ogni tap, mai dopo l'ultimo, quindi un cambio riuscito
    # solo al secondo tentativo veniva comunque riportato come fallito.
    if detect_village_type() == target:
        print(f"[VILLAGGIO] Ora siamo su '{target}'.")
        return True

    print(f"[VILLAGGIO] Cambio fallito dopo {max_attempts} tentativi, siamo ancora su '{detect_village_type()}'.")
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
#   villaggio primario dove ce n'è sempre una sola. Leggere il costo esatto
#   di ognuna per scegliere la più economica si è rivelato inaffidabile,
#   testato offline sugli screenshot del 2026-08-04: stesso tipo di bug OCR
#   già documentato nel villaggio primario ("204 000" letto "#204 000",
#   "8 500" letto "@38" a seconda dello sfondo dietro il pannello
#   semi-trasparente). Deciso con l'utente: si prende semplicemente la
#   PRIMA voce "Muro" trovata scorrendo dall'alto (stessa logica già
#   collaudata di _scroll_to_wall_entry() nel primario, nessuna lettura di
#   cifre) - quando quella voce sale abbastanza di costo, un'altra voce più
#   economica verrà trovata prima al giro successivo.
BUILDER_BADGE_POINT_BB = (1115, 65)  # badge "Miglioramenti", vista di default del Villaggio Costruttori
WALL_DROPDOWN_REGION = {"left": 870, "top": 150, "width": 540, "height": 650}
WALL_DROPDOWN_SCROLL = ((1140, 700), (1140, 300))
WALL_MAX_SCROLL_ATTEMPTS = 8
WALL_ACTION_BAR_REGION = {"left": 300, "top": 760, "width": 1350, "height": 220}
WALL_COST_LABEL_OFFSET = (0, -55)   # dal centro del pulsante "Migliora" al centro dell'etichetta di costo
WALL_COST_LABEL_SIZE = (90, 15)
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
    fa quando l'oro disponibile non basta più. Non ancora ricalibrato dal
    vivo su questa specifica UI (soglia/offset ereditati dal primario, il
    layout del pannello sembra visivamente identico) - se il rilevamento
    risultasse impreciso al primo uso reale, va verificato con uno
    screenshot di debug prima di continuare."""
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


def _scroll_to_wall_entry():
    """Identico a _scroll_to_wall_entry() del villaggio primario: scorre
    la tendina finché non trova la PRIMA voce 'Muro' (qualunque sia il suo
    costo/xN - vedi commento generale sopra sul perché non si cerca la più
    economica). Ritorna il centro della voce trovata, o None."""
    for _ in range(WALL_MAX_SCROLL_ATTEMPTS):
        frame = adb_screenshot()
        center = _find_text_center(frame, WALL_DROPDOWN_REGION, "Muro")
        if center:
            return center
        (x1, y1), (x2, y2) = WALL_DROPDOWN_SCROLL
        adb_swipe(x1, y1, x2, y2, duration_ms=600)
        time.sleep(1.0)
    return None


def try_wall_upgrade():
    """Un giro di upgrade mura nel Villaggio Costruttori: apre la tendina,
    trova la prima voce 'Muro', la seleziona, poi aggiunge mura al batch
    una alla volta ("Aggiungi mura +1", mai +10 - stessa scelta esplicita
    del villaggio primario) finché il costo in oro non diventa rosso
    (fondi insufficienti), infine conferma il pagamento.

    A differenza di try_wall_upgrade() nel villaggio primario: valuta
    sempre e solo oro (nessuna scelta tra due valute, l'Anello da mura non
    viene mai usato), nessun controllo costruttore libero (upgrade sempre
    istantaneo). Ritorna True se ha confermato un upgrade, False se ha
    saltato per qualunque motivo (nessuna eccezione sollevata: l'obiettivo
    è che un fallimento qui non comprometta il ciclo di attacco normale).
    """
    print("[MURA] Apro la tendina miglioramenti...")
    adb_tap(*BUILDER_BADGE_POINT_BB)
    time.sleep(1.5)

    wall_center = _scroll_to_wall_entry()
    if not wall_center:
        print("[MURA] Voce 'Muro' non trovata al primo giro, riprovo riaprendo la tendina...")
        adb_tap(*BUILDER_BADGE_POINT_BB)
        time.sleep(1.0)
        adb_tap(*BUILDER_BADGE_POINT_BB)
        time.sleep(1.5)
        wall_center = _scroll_to_wall_entry()
    if not wall_center:
        print("[MURA] Non ho trovato nessuna voce 'Muro' nella tendina, salto.")
        deselect_all_bb()
        return False

    adb_tap(*wall_center)
    time.sleep(1.5)

    # Selezionare una voce non chiude la tendina (stesso bug UI del
    # villaggio primario): ritoccare il badge la chiude senza deselezionare
    # il muro (stesso "toggle" già usato per aprirla).
    adb_tap(*BUILDER_BADGE_POINT_BB)
    time.sleep(1.5)

    # Selezione singola: 4 pulsanti (Info | Migliora ancora | Migliora oro |
    # Migliora anello) o 5 se compare anche "Selez. Riga" - "Migliora
    # ancora" è sempre il terzultimo in entrambi i casi (stessa posizione
    # relativa verificata dal vivo il 2026-08-04).
    buttons = _find_action_bar_buttons_retry(4, debug_name="bb_selezione")
    if len(buttons) < 4:
        print(f"[MURA] Barra pulsanti inattesa ({len(buttons)} invece di 4-5), salto.")
        deselect_all_bb()
        return False

    ancora_center = buttons[-3]
    adb_tap(*ancora_center)
    time.sleep(1.2)

    # Modalità batch dopo "Migliora ancora": Togli mura -1 | Aggiungi +10 |
    # Aggiungi +1 | Migliora oro | Migliora anello (stessa griglia a 5
    # posizioni del villaggio primario, verificata dal vivo).
    buttons = _find_action_bar_buttons_retry(5, debug_name="bb_batch")
    if len(buttons) < 5:
        print(f"[MURA] Barra pulsanti batch inattesa ({len(buttons)} invece di 5), ritento 'Migliora ancora'...")
        adb_tap(*ancora_center)
        time.sleep(1.5)
        buttons = _find_action_bar_buttons_retry(5, debug_name="bb_batch")
    if len(buttons) < 5:
        print(f"[MURA] Barra pulsanti batch ancora inattesa ({len(buttons)} invece di 5), salto.")
        deselect_all_bb()
        return False

    add_one_point = buttons[2]
    remove_one_point = buttons[0]
    pay_point = buttons[3]  # sempre oro, mai l'Anello da mura (vedi commento in cima)

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

    print(f"[MURA] Punto a {target_count} mura, pago in oro.")

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

    print(f"[MURA] Confermato upgrade di {target_count} mura, pagato in oro.")
    send_telegram(f"🧱 Villaggio Costruttori: upgrade di {target_count} mura (oro).")

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
      successivo è pronto - si può schierare SUBITO, il gioco lo permette
      anche durante questo countdown, non serve aspettare che scada);
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
    # Rete di sicurezza: se un popup "Bonus stella!" del ciclo precedente è
    # rimasto aperto più a lungo del previsto, questo tap lo chiude prima di
    # provare "Attacco!" (altrimenti il tap su ATTACK_BUTTON cade a vuoto
    # fuori dal popup e il ciclo si blocca) - a vuoto se non serve.
    adb_tap(*STAR_BONUS_OK_BUTTON)
    time.sleep(0.3)

    print("[ATTACK] Tocco 'Attacco!'...")
    adb_tap(*ATTACK_BUTTON)
    time.sleep(1.2)

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
        print("[RAID 2/2] Secondo raid pronto, schiero subito...")
        deploy_wave()
        print("[RAID 2/2] Aspetto la fine della battaglia (controllo attivo)...")
        wait_for_next_screen()

    print("[ATTACK] Torno al villaggio...")
    adb_tap(*RETURN_HOME_BUTTON)
    time.sleep(1.6)
    print("[ATTACK] Chiudo eventuale popup 'Bonus stella!' (tap a vuoto se non c'è)...")
    adb_tap(*STAR_BONUS_OK_BUTTON)
    time.sleep(2.5)
    # Il popup a volte compare con un ritardo maggiore del previsto (visto
    # dal vivo: il primo tap è arrivato troppo presto, il popup è rimasto
    # aperto e ha bloccato il tap "Attacco!" del ciclo successivo, caduto a
    # vuoto fuori dal popup). Secondo tentativo dopo un'attesa più lunga -
    # a vuoto se non serve.
    adb_tap(*STAR_BONUS_OK_BUTTON)
    time.sleep(1.0)


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
        switch_to_village("costruttore")
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
