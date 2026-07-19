import os
import sys
import json
import time
import random
import shutil
import subprocess
import numpy as np
import cv2
import pytesseract
import requests   # per Telegram

# La console di Windows lanciata da Task Scheduler puo' usare una code page
# che non sa stampare le emoji usate nei messaggi di stato (es. "✅"): senza
# questo, un print con un'emoji manda un'eccezione non gestita che finiva
# dritta nel blocco finally piu' in basso, bloccando il processo per sempre
# in attesa di un INVIO che in un avvio automatico non arriva mai. Scoperto
# durante un test dal vivo della v1.6 (il bot restava "appeso" a fine
# sessione invece di fermarsi).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Aggiornare ad ogni modifica funzionale del bot (anche nel README).
VERSION = "1.7"

# ==========================
# CONFIGURAZIONE TELEGRAM
# ==========================
# Token e chat id NON sono hardcoded: si leggono dalle variabili d'ambiente
# TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID, dichiarate nel file 'cred' (vedi README).

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    sys.exit(
        "Errore: variabili d'ambiente TELEGRAM_BOT_TOKEN e/o TELEGRAM_CHAT_ID mancanti.\n"
        "Crea un file 'cred' (vedi README) e lancia 'source cred' prima di avviare il bot."
    )

def send_telegram(message: str):
    """Manda un messaggio Telegram al tuo chat_id."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        resp = requests.post(url, data=data, timeout=10)
        print("[TELEGRAM] Richiesta a:", resp.url)
        print("[TELEGRAM] Status:", resp.status_code, "-", resp.text)

        if resp.status_code == 200:
            print("[TELEGRAM] Notifica inviata!")
        else:
            print("[TELEGRAM] Errore HTTP:", resp.status_code)

    except Exception as e:
        print("[TELEGRAM] Errore Telegram:", e)

# ==========================
# CONFIGURAZIONE GENERALE
# ==========================

def find_tesseract_cmd():
    """Trova l'eseguibile di Tesseract."""
    found = shutil.which("tesseract")
    if found:
        return found

    candidates = [
        "/opt/homebrew/bin/tesseract",   # Homebrew su Apple Silicon (M1/M2/M3)
        "/usr/local/bin/tesseract",      # Homebrew su Mac Intel
        "/usr/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",   # Windows
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "Tesseract non trovato. Installalo con: brew install tesseract\n"
        "Poi verifica il percorso con: which tesseract"
    )


pytesseract.pytesseract.tesseract_cmd = find_tesseract_cmd()

# ==========================
# CONFIGURAZIONE ADB (BlueStacks)
# ==========================
# Il bot non legge/clicca più lo schermo reale del Mac: pilota l'emulatore
# Android via ADB (screencap + input tap/swipe). Per questo BlueStacks può
# restare minimizzato o nascosto: il bot funziona lo stesso.
#
# Requisito: in BlueStacks vai su Impostazioni -> Avanzate -> abilita
# "Android Debug Bridge".


def find_adb_cmd():
    """Trova l'eseguibile adb: prima nel PATH, poi quello incluso in BlueStacks."""
    found = shutil.which("adb")
    if found:
        return found

    candidates = [
        "/Applications/BlueStacks.app/Contents/MacOS/hd-adb",       # Mac
        r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",               # Windows
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "adb non trovato. Installa Android Platform Tools (brew install "
        "android-platform-tools) oppure verifica che BlueStacks sia installato "
        "nel percorso predefinito."
    )


ADB_CMD = find_adb_cmd()


def adb(*args, device=None, timeout=15):
    """Esegue un comando adb e ritorna il CompletedProcess (stdout/stderr in bytes)."""
    cmd = [ADB_CMD]
    if device:
        cmd += ["-s", device]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)


def find_device():
    """Ritorna il primo device Android connesso via adb (es. l'istanza BlueStacks)."""
    result = adb("devices")
    lines = result.stdout.decode(errors="ignore").strip().splitlines()[1:]
    for line in lines:
        if line.strip().endswith("device"):
            return line.split()[0]

    raise RuntimeError(
        "Nessun device ADB trovato. Verifica che BlueStacks sia avviato e che "
        "'Android Debug Bridge' sia abilitato in Impostazioni -> Avanzate."
    )


DEVICE = find_device()
print(f"[ADB] Device connesso: {DEVICE}")


def adb_screenshot():
    """Cattura lo schermo dell'emulatore e ritorna un array numpy BGR (OpenCV)."""
    result = adb("exec-out", "screencap", "-p", device=DEVICE)
    img_array = np.frombuffer(result.stdout, dtype=np.uint8)
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("Screenshot ADB non decodificabile (screencap fallito?).")
    return frame


def adb_tap(x, y):
    adb("shell", "input", "tap", str(x), str(y), device=DEVICE)


def adb_tap_jittered(x, y, jitter=None):
    """Come adb_tap, ma con un piccolo scarto casuale di posizione (DEPLOY_JITTER_PX
    di default): usato per lo schieramento, per non tappare sempre il pixel
    esatto identico ad ogni attacco. Non usarlo sui pulsanti dell'interfaccia
    (troppo piccoli, un tap fuori bersaglio li mancherebbe).
    """
    if jitter is None:
        jitter = DEPLOY_JITTER_PX
    adb_tap(x + random.randint(-jitter, jitter), y + random.randint(-jitter, jitter))


def adb_swipe(x1, y1, x2, y2, duration_ms=600):
    adb(
        "shell", "input", "swipe",
        str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        device=DEVICE,
    )


# ==========================
# COORDINATE (calibrate dal vivo su BlueStacks, screenshot 1920x1080)
# ==========================
# A differenza della vecchia versione Mac, qui non c'e' una dashboard fissa
# da leggere in continuazione: il flusso e' quello del matchmaking di Clash
# of Clans (cerca avversario -> valuta bottino -> attacca o salta -> risultato
# -> torna al villaggio), quindi tutte le coordinate/sequenze sono state
# riscritte per questo flusso.

ATTACK_BUTTON = (135, 1020)          # "Attacco!" nel villaggio
FIND_MATCH_BUTTON = (335, 800)       # "Trova una partita" (tab Multigiocatore)
CONFIRM_ATTACK_BUTTON = (1697, 960)  # "Attacco!" nella schermata riepilogo esercito
SKIP_BUTTON = (1745, 780)            # "Avanti" - scarta l'avversario e ricerca
RETURN_HOME_BUTTON = (955, 985)      # "Torna al villaggio" a fine battaglia

# Regioni "Bottino disponibile" nella schermata di scouting, prima che la
# battaglia inizi. Formato (left, top, width, height). Calibrate dal vivo
# (screenshot 1920x1080 su BlueStacks).
OCR_REGION_ELIXIR = {
    "left": 88,
    "top": 203,
    "width": 180,
    "height": 30,
}
OCR_REGION_GOLD = {
    "left": 68,
    "top": 149,
    "width": 180,
    "height": 30,
}
OCR_REGION_DARK_ELIXIR = {
    "left": 61,
    "top": 263,
    "width": 180,
    "height": 30,
}

# Regioni delle risorse in casa (barra in alto a destra nel villaggio),
# usate per capire quale risorsa scarseggia di più prima di iniziare a
# farmare. Calibrate dal vivo (screenshot 1920x1080 su BlueStacks).
HOME_REGION_GOLD = {
    "left": 1595,
    "top": 42,
    "width": 220,
    "height": 34,
}
HOME_REGION_ELIXIR = {
    "left": 1595,
    "top": 145,
    "width": 220,
    "height": 34,
}
HOME_REGION_DARK_ELIXIR = {
    "left": 1655,
    "top": 243,
    "width": 170,
    "height": 34,
}

# Barra truppe/eroi in basso: x di ogni slot (y fissa = TROOP_BAR_Y).
# TROOP_SLOTS sono le truppe, HERO_SLOTS gli eroi (regina, re, gran
# sorvegliante, campionessa). Esercito: 10 draghi elettrici + 1 macchina
# d'assedio (mongolfiera d'assedio) - ogni slot ha il proprio numero di tap
# (10 per il drago, 1 per la macchina d'assedio, che e' un solo mezzo).
# Posizioni calibrate dal vivo su screenshot ADB reale (non solo assunte).
TROOP_BAR_Y = 975
TROOP_SLOTS = [
    (197, 17),   # drago elettrico x10 - piu' tap che draghi (17, tutti i
                 # DEPLOY_POINTS disponibili): nei test dal vivo con 10 tap
                 # ne mancavano 4, con 14 ne mancavano 2 - alcuni tap non
                 # arrivano mai a segno (non e' la zona rossa), quindi se ne
                 # mandano di piu' del necessario. I tap in eccesso oltre
                 # alle truppe realmente disponibili non fanno nulla.
    (340, 6),    # macchina d'assedio (mongolfiera d'assedio): un solo mezzo,
                 # ma 6 tap su punti diversi. Le macchine d'assedio hanno
                 # regole di piazzamento piu' rigide dei draghi (visto dal
                 # vivo: "non puoi piazzare nella zona rossa" su punti dove
                 # i draghi non hanno problemi), quindi le servono piu'
                 # tentativi sparsi per trovarne uno valido.
]
HERO_SLOTS = [483, 626, 785, 928]

# Zona di schieramento: tutte le truppe vengono piazzate qui, in un unico
# passaggio. Questi punti non sono generici: sono calibrati apposta sul
# bordo PIU' ESTERNO del campo di battaglia (il confine della mappa, non
# il perimetro della base), cosi' la zona rossa - che dipende dalle mura
# ed edifici di ogni singola base - non li tocca mai, qualunque sia la
# base incontrata (quella testata con successo: 93% danno, 2 stelle).
# Un tentativo di spostarli "al buio" piu' lontano dal bordo per un
# problema di zona rossa segnalato su una base specifica si e' rivelato
# un errore: alcuni punti finivano fuori dall'area valida. Tornati alle
# coordinate originali.
DEPLOY_POINTS = [
    (1300, 550), (1350, 500), (1400, 450), (1450, 400), (1500, 350), (1550, 300),
    (1600, 250), (1650, 200),  # continuano la stessa diagonale verso l'alto
    (1400, 600), (1350, 650), (1300, 700), (1250, 720), (1200, 740),
    (1150, 760), (1100, 780), (1050, 800), (1000, 820),
]
# Gli eroi usavano un unico punto fisso (1350, 550): su alcune basi quel
# punto e' troppo vicino alle mura (non e' sul bordo esterno come i
# DEPLOY_POINTS sopra) e nessun eroe veniva schierato - scoperto dal vivo
# controllando manualmente dove cadeva il tap. Ora pescano dagli stessi
# DEPLOY_POINTS che funzionano in modo affidabile per le truppe.

# Niente scarto di posizione casuale sui punti di schieramento: sono
# calibrati esattamente sul bordo esterno della mappa (vedi sopra), quindi
# qualunque jitter, anche piccolo, rischia di spingere il tap oltre quel
# bordo nel vuoto non giocabile - provato dal vivo sia con 14px che con
# 5px, in entrambi i casi alcune truppe non venivano schierate. La
# randomizzazione "leggera" della v1.7 resta sull'ordine di schieramento
# (mescolato) e sui tempi tra un tap e l'altro (variabili), non sulla
# posizione. Randomizzazione piu' spinta pianificata per la v1.8.
DEPLOY_JITTER_PX = 0

# Scroll verso il basso appena inizia la battaglia, prima di schierare:
# porta la vista nella posizione giusta per raggiungere la zona di
# schieramento in basso a destra. Scalato dalle coordinate Mac originali
# (563,500)->(563,250) su 1440x900; da ricalibrare se non allinea bene.
DRAG_START = (750, 600)
DRAG_END = (750, 300)
DRAG_DURATION = 0.6

# Pulsante rosso "Termina battaglia" / "Resa" (stessa posizione, testo
# diverso a seconda che tu abbia gia' schierato truppe o no). Se hai gia'
# schierato truppe, il gioco chiede conferma con un popup "Arrendersi?"
# (Annulla/OK): il pulsante OK verde e' a CONFIRM_END_BATTLE_BUTTON.
END_BATTLE_BUTTON = (140, 785)
CONFIRM_END_BATTLE_BUTTON = (1150, 670)

# Parametri di farming regolabili dalla dashboard web (sezione Impostazioni):
# letti da config.json accanto allo script, con questi valori come default
# se il file non c'e' o e' incompleto. Le soglie "threshold_*" sono il
# bottino minimo del bersaglio per attaccare (una per risorsa, usata solo
# quella della risorsa prioritaria della sessione); le "home_low_*" sono
# la soglia sotto la quale una risorsa in casa e' considerata scarsa.
CONFIG_FILE = "config.json"
_CONFIG_DEFAULTS = {
    "threshold_gold": 800000,
    "threshold_elixir": 800000,
    "threshold_dark_elixir": 3000,
    "home_low_gold": 300000,
    "home_low_elixir": 300000,
    "home_low_dark_elixir": 1500,
    "max_triggers": 20,
    "session_duration_minutes": 50,
}


def load_config():
    config = dict(_CONFIG_DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        config.update({k: v for k, v in data.items() if k in _CONFIG_DEFAULTS})
    except (FileNotFoundError, ValueError):
        pass
    return config


_config = load_config()

MAX_SKIP_ATTEMPTS = 15       # avversari da scartare al massimo prima di attaccare comunque
CLICK_INTERVAL_RANGE = (0.10, 0.22)  # intervallo casuale tra un tap e l'altro, invece di uno fisso
BATTLE_START_MAX_WAIT = 2.0   # attesa fissa dopo aver accettato un bersaglio sopra soglia
BATTLE_DURATION_WAIT = (60.0, 90.0)  # attesa (min, max) prima di terminare la battaglia da soli

SESSION_DURATION = _config["session_duration_minutes"] * 60
MAX_TRIGGERS = _config["max_triggers"]         # numero di attacchi dopo cui il bot si ferma da solo
trigger_count = 0

# Risorsa su cui la sessione e' concentrata (decisa da determine_priority_resource()
# in main(), prima del loop di attacco: quella piu' scarsa in casa rispetto
# alle soglie home_low_*, o "elixir" di default se nessuna scarseggia).
priority_resource = "elixir"

# Bottino stimato accumulato nella sessione (somma del bottino "disponibile"
# visto in fase di scouting sui bersagli attaccati, non il bottino
# realmente incassato a fine battaglia: il gioco non lo espone via OCR
# semplice, quindi va trattato come stima, non come dato esatto).
session_totals = {"gold": 0, "elixir": 0, "dark_elixir": 0}

# Stato esposto alla dashboard web (letto da fuori via SSH, non dal bot
# stesso): ultime risorse lette e orario di partenza sessione.
STATUS_FILE = "status.json"
HISTORY_FILE = "history.json"
last_resources = {"gold": None, "elixir": None, "dark_elixir": None}
session_start_time = None


def write_status(running):
    """Scrive lo stato corrente su file, letto poi dalla dashboard web."""
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({
                "running": running,
                "version": VERSION,
                "session_start_time": session_start_time,
                "trigger_count": trigger_count,
                "priority_resource": priority_resource,
                "last_resources": last_resources,
                "updated_at": time.time(),
            }, f)
    except Exception as e:
        print(f"[STATUS] Errore scrittura {STATUS_FILE}: {e}")


def append_history_entry():
    """Aggiunge un riepilogo della sessione appena conclusa a history.json,
    letto dalla dashboard per lo storico. Tiene solo le ultime 50 sessioni.
    """
    entry = {
        "start": session_start_time,
        "end": time.time(),
        "duration_minutes": round((time.time() - session_start_time) / 60, 1),
        "trigger_count": trigger_count,
        "priority_resource": priority_resource,
        "totals": session_totals,
        "version": VERSION,
    }
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        history.append(entry)
        history = history[-50:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except Exception as e:
        print(f"[HISTORY] Errore scrittura {HISTORY_FILE}: {e}")


# ==========================
# FUNZIONI
# ==========================

# Pixel usato per capire se siamo nel villaggio (home) oppure in una
# schermata di ricerca/battaglia. In quel punto (dentro il pulsante in
# basso a sinistra) il colore e' arancione/oro acceso nel villaggio
# (R-B ~140) e blu altrove in scouting/battaglia (R-B ~ -115/-166).
# Durante la schermata di caricamento "Ricerca avversari..." il pixel e'
# grigio neutro (R-B ~6): un semplice confronto R>B lo classificava per
# errore come "home" (falso positivo che causava lo schieramento sulla
# base propria). La soglia sulla differenza evita l'ambiguita'.
HOME_CHECK_POINT = (135, 1010)
HOME_CHECK_MIN_DIFF = 50


def _home_pixel_says_home():
    frame = adb_screenshot()
    x, y = HOME_CHECK_POINT
    b, g, r = frame[y, x]
    return (int(r) - int(b)) > HOME_CHECK_MIN_DIFF


def is_home_screen():
    """True se siamo nel villaggio (non in ricerca/battaglia).

    Richiede due letture concordi a distanza di tempo per evitare falsi
    positivi durante i fotogrammi di transizione tra una schermata e
    l'altra (es. subito dopo aver toccato 'Avanti').
    """
    if not _home_pixel_says_home():
        return False
    time.sleep(0.4)
    return _home_pixel_says_home()


def _ocr_region_to_int(frame, region, debug_name):
    """Legge un numero da una regione dello schermo (bottino/risorse). Il
    testo del gioco e' bianco con bordo nero su uno sfondo fotografico
    molto rumoroso: invece di un semplice threshold in scala di grigi,
    isoliamo i pixel bianchi in HSV (bassa saturazione, alta luminosita'),
    che si e' rivelato molto piu' affidabile nei test dal vivo.

    `debug_name` determina il file debug_<nome>.png scritto ad ogni
    lettura, utile per calibrare/verificare la regione dal vivo.
    """
    l, t = region["left"], region["top"]
    w, h = region["width"], region["height"]
    crop = frame[t:t + h, l:l + w]

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    lower = np.array([0, 0, 180])
    upper = np.array([180, 60, 255])
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.resize(mask, None, fx=5.0, fy=5.0, interpolation=cv2.INTER_CUBIC)
    mask = cv2.copyMakeBorder(mask, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=0)

    cv2.imwrite(f"debug_{debug_name}.png", mask)

    # psm 7 (singola riga) falliva silenziosamente (zero blocchi di testo
    # trovati) sui numeri con separatore delle migliaia " " quando la parte
    # bianca del testo supera circa il 30% dell'area della regione (es.
    # "26 000 000" in casa), pur funzionando su numeri piu' corti come
    # "321 946": scoperto testando dal vivo le nuove regioni di oro/dark
    # elisir. psm 13 (raw line, bypassa l'euristica di layout di Tesseract)
    # legge correttamente in entrambi i casi.
    ocr_config = "--oem 3 --psm 13 -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(mask, config=ocr_config)

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def read_available_resources():
    """Legge oro, elisir e dark elisir 'disponibili' nella schermata di
    scouting, da un unico screenshot (tre crop invece di tre screenshot,
    per non rallentare il loop di scouting che ha un budget di tempo).
    """
    frame = adb_screenshot()
    return {
        "gold": _ocr_region_to_int(frame, OCR_REGION_GOLD, "gold"),
        "elixir": _ocr_region_to_int(frame, OCR_REGION_ELIXIR, "elixir"),
        "dark_elixir": _ocr_region_to_int(frame, OCR_REGION_DARK_ELIXIR, "dark_elixir"),
    }


def read_home_resources():
    """Legge oro, elisir e dark elisir attualmente in casa (barra risorse
    nel villaggio), usati da determine_priority_resource() per capire quale
    risorsa scarseggia di piu' prima di iniziare a farmare.
    """
    frame = adb_screenshot()
    return {
        "gold": _ocr_region_to_int(frame, HOME_REGION_GOLD, "home_gold"),
        "elixir": _ocr_region_to_int(frame, HOME_REGION_ELIXIR, "home_elixir"),
        "dark_elixir": _ocr_region_to_int(frame, HOME_REGION_DARK_ELIXIR, "home_dark_elixir"),
    }


def determine_priority_resource():
    """Decide su quale risorsa concentrare la sessione: quella con il
    deficit maggiore rispetto alla propria soglia 'basso' (home_low_*). Se
    nessuna risorsa e' sotto soglia (o l'OCR fallisce su tutte), resta
    l'elisir di default (stesso comportamento di prima di questa funzione).
    """
    home = read_home_resources()
    if all(v is None for v in home.values()):
        # Lettura completamente vuota: capita se il villaggio non e'
        # ancora del tutto stabile a schermo (animazioni, popup del primo
        # accesso del giorno) nonostante is_home_screen() dica gia' di si'.
        # Un solo ritentativo dopo una pausa breve, invece di arrendersi
        # subito al fallback.
        time.sleep(2.0)
        home = read_home_resources()

    deficits = {}
    for resource in ("gold", "elixir", "dark_elixir"):
        amount = home.get(resource)
        low = _config[f"home_low_{resource}"]
        if amount is not None and amount < low:
            deficits[resource] = low - amount

    if not deficits:
        return "elixir", home
    return max(deficits, key=deficits.get), home


def scroll_down_by_drag():
    """Scroll verso il basso appena inizia la battaglia, per portare la
    vista nella posizione giusta prima di schierare le truppe.
    """
    print("[ACTION] Scroll verso il basso...")
    adb_swipe(DRAG_START[0], DRAG_START[1], DRAG_END[0], DRAG_END[1], int(DRAG_DURATION * 1000))
    time.sleep(1.0)


def deploy_army():
    """Scrolla nella posizione giusta, poi schiera TUTTE le truppe e gli
    eroi in un unico passaggio, sempre nella stessa zona (lato destro/basso
    della base) invece di sperimentare posizioni diverse ad ogni attacco.

    I tap di schieramento hanno un piccolo scarto casuale di posizione e
    ordine (DEPLOY_JITTER_PX, ordine mescolato) e i tempi tra un tap e
    l'altro variano in un range invece di essere fissi: randomizzazione
    "leggera" per rendere il pattern meno riconoscibile (v1.7).
    """
    scroll_down_by_drag()

    print("[DEPLOY] Schiero le truppe...")
    for slot_x, taps in TROOP_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(random.uniform(0.12, 0.20))
        # Mescola PRIMA di tagliare a `taps` elementi, non dopo: altrimenti
        # con taps < len(DEPLOY_POINTS) si provano sempre e solo gli stessi
        # primi punti della lista (mai variati) - bug trovato dal vivo con
        # la macchina d'assedio, che aveva sempre gli stessi 3 punti e,
        # essendo piu' esigente dei draghi su dove puo' atterrare, falliva
        # sempre allo stesso modo. Ora pesca da tutta la lista.
        deploy_points = list(DEPLOY_POINTS)
        random.shuffle(deploy_points)
        deploy_points = deploy_points[:taps]
        for (dx, dy) in deploy_points:
            adb_tap_jittered(dx, dy)
            time.sleep(random.uniform(*CLICK_INTERVAL_RANGE))

    print("[DEPLOY] Schiero gli eroi...")
    hero_points = list(DEPLOY_POINTS)
    random.shuffle(hero_points)
    point_idx = 0
    for slot_x in HERO_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(random.uniform(0.12, 0.20))
        # 2 tap su punti diversi invece di uno solo: se il primo non va a
        # segno (stesso problema visto con le truppe), il secondo copre.
        for _ in range(2):
            dx, dy = hero_points[point_idx % len(hero_points)]
            point_idx += 1
            adb_tap_jittered(dx, dy)
            time.sleep(random.uniform(*CLICK_INTERVAL_RANGE))

    time.sleep(random.uniform(1.6, 2.4))

    print("[DEPLOY] Attivo le abilità eroi...")
    for slot_x in HERO_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(random.uniform(0.16, 0.26))


# Il countdown di matchmaking del gioco dura ~28-30s da quando un avversario
# viene trovato: se il loop di skip lo supera, la battaglia parte da sola
# mentre lo script pensa ancora di essere in fase di scouting. Per questo
# ogni iterazione ricontrolla anche il tempo trascorso, non solo il numero
# di tentativi.
SCOUT_TIME_BUDGET = 20.0


def find_and_evaluate_opponent():
    """Cerca un avversario e valuta il bottino disponibile della risorsa
    prioritaria della sessione (priority_resource): scarta i bersagli sotto
    soglia (tasto 'Avanti') finché non ne trova uno buono, esaurisce i
    tentativi, o rischia di far scadere il countdown. Le altre due risorse
    vengono lette e loggate ma non influenzano la decisione. Ritorna True
    se conviene procedere verso la battaglia.
    """
    global last_resources
    threshold = _config[f"threshold_{priority_resource}"]
    start = time.time()
    for attempt in range(1, MAX_SKIP_ATTEMPTS + 1):
        time.sleep(0.8)

        if is_home_screen():
            print("[SCOUT] Siamo tornati al villaggio inaspettatamente, interrompo la ricerca.")
            return False

        resources = read_available_resources()
        loot = resources.get(priority_resource)
        print(f"[SCOUT] Tentativo {attempt}/{MAX_SKIP_ATTEMPTS} - risorsa prioritaria ({priority_resource}): {loot} - tutte: {resources}")
        if any(v is not None for v in resources.values()):
            last_resources = resources

        if loot is not None and loot >= threshold:
            print(f"[SCOUT] {loot} >= {threshold} -> attacco questa base")
            return True

        if time.time() - start > SCOUT_TIME_BUDGET:
            print("[SCOUT] Budget di tempo scouting esaurito, attacco comunque l'ultima base trovata.")
            return True

        print("[SCOUT] Sotto soglia (o non letto) -> cerco un altro avversario")
        adb_tap(*SKIP_BUTTON)
        time.sleep(1.2)

    print("[SCOUT] Raggiunto il limite di tentativi, attacco comunque l'ultima base trovata.")
    return True


def wait_for_battle_start(fixed_wait=BATTLE_START_MAX_WAIT):
    """Aspetta che il countdown di matchmaking finisca e la battaglia
    inizi davvero.

    Provare a rilevare la transizione leggendo lo schermo (OCR sul
    bottino, colore di icone) si è rivelato inaffidabile nei test dal
    vivo: l'OCR a volte legge numeri residui/rumore invece di None, e le
    decorazioni della base (a tema, es. Pasqua/Natale) possono avere
    colori identici a quelli delle icone dell'interfaccia, generando falsi
    positivi/negativi. Molto più robusto aspettare semplicemente il tempo
    fisso del countdown di gioco (~28-30s) e poi verificare solo che non
    siamo tornati al villaggio (quell'unico controllo si è dimostrato
    affidabile).
    """
    print(f"[WAIT] Aspetto {fixed_wait:.0f}s che il countdown finisca...")
    time.sleep(fixed_wait)

    if is_home_screen():
        print("[WAIT] Siamo al villaggio, la battaglia non è mai iniziata.")
        return False
    return True


def run_attack():
    """Un ciclo completo: cerca avversario, valuta, attacca, aspetta la
    fine della battaglia, torna al villaggio. Ogni fase verifica lo stato
    reale dello schermo prima di procedere: se qualcosa va storto (es. si
    torna al villaggio prima del previsto) il ciclo si interrompe subito
    invece di continuare a schierare truppe alla cieca.
    """
    # A volte un popup imprevisto sopra al villaggio (es. "Miglioramento
    # completato!", offerte, eventi) assorbe il tap su "Attacco!": la
    # sequenza di tap successivi (pensati per le schermate seguenti) allora
    # cade ancora sul villaggio, rischiando di premere pulsanti sbagliati
    # (es. il Negozio, se la sua posizione coincide con una di quelle
    # coordinate). Per questo verifichiamo che il tap abbia funzionato
    # davvero (siamo usciti dal villaggio) prima di proseguire, invece di
    # fidarci ciecamente del solo tempo di attesa.
    adb_tap(*ATTACK_BUTTON)
    time.sleep(1.5)

    if is_home_screen():
        print("[ATTACK] 'Attacco!' non sembra essersi aperto (popup imprevisto?), riprovo...")
        adb_tap(*ATTACK_BUTTON)
        time.sleep(1.5)

        if is_home_screen():
            print("[ATTACK] Ancora al villaggio dopo il secondo tentativo, salto questo ciclo.")
            send_telegram("⚠️ Non riesco ad aprire la schermata di attacco (forse un popup blocca il villaggio). Salto un ciclo, controlla lo schermo se continua a succedere.")
            return

    adb_tap(*FIND_MATCH_BUTTON)
    time.sleep(2.0)
    adb_tap(*CONFIRM_ATTACK_BUTTON)
    time.sleep(3.0)

    if not find_and_evaluate_opponent():
        print("[ATTACK] Scouting interrotto, salto questo ciclo.")
        return

    for resource, amount in last_resources.items():
        if amount is not None:
            session_totals[resource] += amount

    if not wait_for_battle_start():
        print("[ATTACK] La battaglia non è iniziata come previsto, salto lo schieramento.")
        return

    if is_home_screen():
        print("[ATTACK] Siamo al villaggio invece che in battaglia: non schiero nulla.")
        return

    deploy_army()

    wait_time = random.uniform(*BATTLE_DURATION_WAIT)
    print(f"[WAIT] Aspetto ~{wait_time:.0f}s (tempo casuale, per sembrare più umano) prima di terminare...")
    time.sleep(wait_time)

    print("[ACTION] Termino la battaglia...")
    adb_tap(*END_BATTLE_BUTTON)
    time.sleep(1.5)
    # Se abbiamo schierato truppe, compare il popup di conferma "Arrendersi?":
    # questo tap non fa nulla se il popup non c'è (tocca lo sfondo del risultato).
    adb_tap(*CONFIRM_END_BATTLE_BUTTON)
    time.sleep(2.0)

    print("[ACTION] Torno al villaggio...")
    adb_tap(*RETURN_HOME_BUTTON)
    time.sleep(2.0)
    adb_tap(*RETURN_HOME_BUTTON)  # nel caso serva un secondo tap (es. schermata forziere)
    time.sleep(2.0)


def calibrate_coordinates():
    """
    Helper di calibrazione: salva uno screenshot dell'emulatore
    (calibrate.png, risoluzione 1920x1080) su cui misurare i pixel dei
    punti che ti servono, con un qualsiasi editor/visualizzatore di
    immagini che mostri la posizione del cursore (es. Anteprima su Mac,
    oppure GIMP/Photoshop). Aggiorna poi le costanti in cima al file.

    Per calibrare OCR_REGION_GOLD/OCR_REGION_DARK_ELIXIR lancialo mentre sei
    nella schermata di scouting (bottino disponibile del bersaglio); per
    HOME_REGION_GOLD/HOME_REGION_ELIXIR/HOME_REGION_DARK_ELIXIR lancialo
    mentre sei nel villaggio (barra risorse in alto a sinistra). Ogni volta
    misura solo la regione che ti serve in quel momento sullo screenshot.

    Per usarlo: lancia lo script con  python BOT_COMPLETO_MAC.py --calibrate
    """
    print("=== MODALITÀ CALIBRAZIONE ===")
    frame = adb_screenshot()
    h, w = frame.shape[:2]
    cv2.imwrite("calibrate.png", frame)
    print(f"Screenshot salvato in calibrate.png ({w}x{h}).")
    print("Aprilo con un visualizzatore che mostra le coordinate del cursore")
    print("per misurare i punti che ti servono, poi aggiorna le costanti nello script.")


def main():
    global trigger_count, session_start_time, priority_resource

    print(f"=== OCR BOT (ADB / BlueStacks) - v{VERSION} ===")
    print("debug_<risorsa>.png viene aggiornato ad ogni lettura OCR")
    print("Ctrl + C per interrompere.\n")

    # Appena il gioco viene lanciato (run_bot.bat) il villaggio puo' metterci
    # ancora qualche secondo a stabilizzarsi (animazioni, popup del primo
    # accesso del giorno): aspettiamo che sia davvero pronto prima di
    # leggere le risorse, invece di fidarci ciecamente del tempo fisso gia'
    # atteso dal .bat.
    print("[HOME] Attendo che il villaggio sia pronto...")
    for _ in range(15):
        if is_home_screen():
            break
        time.sleep(1.0)

    priority_resource, home = determine_priority_resource()
    print(f"[HOME] Risorse in casa: {home} -> risorsa prioritaria della sessione: {priority_resource}")

    start_time = time.time()
    session_start_time = start_time
    write_status(running=True)
    send_telegram(f"▶️ Bot avviato (v{VERSION}). Risorsa prioritaria: {priority_resource}. Farà al massimo {MAX_TRIGGERS} attacchi o {int(SESSION_DURATION/60)} minuti.")

    # Se ADB/BlueStacks va giu' a meta' sessione (es. crash dell'emulatore),
    # ogni attacco fallisce subito con un'eccezione: senza un limite, il
    # ciclo riprovava ogni 5s fino a SESSION_DURATION, mandando un messaggio
    # Telegram di errore ad ogni tentativo (decine in pochi minuti). Scoperto
    # dal vivo durante un test. Dopo N errori di fila ci si ferma con un
    # solo avviso, invece di continuare a martellare alla cieca.
    MAX_CONSECUTIVE_ERRORS = 3
    consecutive_errors = 0

    while True:
        now = time.time()

        if now - start_time > SESSION_DURATION:
            msg = "Sono passati 50 minuti, fermo il bot per timeout."
            print(f"\n[STOP] {msg}")
            send_telegram(f"⏱ {msg} Attacchi totali: {trigger_count}")
            write_status(running=False)
            append_history_entry()
            break

        trigger_count += 1
        print(f"\n[ATTACCO {trigger_count}/{MAX_TRIGGERS}]")

        try:
            run_attack()
        except Exception as e:
            consecutive_errors += 1
            print(f"[ERRORE] {e}")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                msg = f"Troppi errori di fila ({consecutive_errors}), mi fermo invece di continuare a riprovare alla cieca."
                print(f"[STOP] {msg}")
                send_telegram(f"🛑 {msg} Ultimo errore: {e}\nControlla che BlueStacks/ADB siano ok.")
                write_status(running=False)
                append_history_entry()
                break
            send_telegram(f"⚠️ Errore durante l'attacco {trigger_count}: {e}")
            write_status(running=True)
            time.sleep(5.0)
            continue

        consecutive_errors = 0
        write_status(running=True)

        if trigger_count >= MAX_TRIGGERS:
            msg = f"✅ Bot ha finito di farmare. Raggiunti {MAX_TRIGGERS} attacchi."
            print(f"[STOP] {msg}")
            send_telegram(msg)
            write_status(running=False)
            append_history_entry()
            break


if __name__ == "__main__":
    import sys

    if "--calibrate" in sys.argv:
        calibrate_coordinates()
        sys.exit(0)

    try:
        main()
    except KeyboardInterrupt:
        print("\nChiuso dall'utente.")
        send_telegram("⛔ Bot interrotto manualmente dall'utente.")
        write_status(running=False)
    finally:
        # sys.stdin.isatty() sembrava un modo per distinguere un avvio
        # interattivo da uno in background, ma la finestra di console aperta
        # da Task Scheduler (run_bot.bat, sia da Telegram che dalla
        # dashboard) e' anch'essa una console vera: isatty() risultava True
        # anche li', quindi il bot restava bloccato per sempre in attesa di
        # un INVIO che nessuno avrebbe mai premuto (scoperto perche' un
        # avvio di test non si fermava mai da solo). L'attesa ora e'
        # esplicita, solo per chi lancia lo script a mano con questo flag.
        if "--pause-on-exit" in sys.argv:
            input("Script terminato. Premi INVIO per chiudere la finestra...")