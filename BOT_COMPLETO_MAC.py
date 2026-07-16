import os
import sys
import time
import random
import shutil
import subprocess
import numpy as np
import cv2
import pytesseract
import requests   # per Telegram

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
        "/Applications/BlueStacks.app/Contents/MacOS/hd-adb",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "adb non trovato. Installa Android Platform Tools (brew install "
        "android-platform-tools) oppure verifica che BlueStacks sia in /Applications."
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

# Regione "Bottino disponibile" (elisir) nella schermata di scouting,
# prima che la battaglia inizi. Formato (left, top, width, height).
OCR_REGION = {
    "left": 88,
    "top": 203,
    "width": 180,
    "height": 30,
}

# Barra truppe/eroi in basso: x di ogni slot (y fissa = TROOP_BAR_Y).
# I primi TROOP_SLOTS sono le truppe (drago, barile, macchina d'assedio, ...),
# gli HERO_SLOTS gli eroi (regina, re, gran sorvegliante, campionessa).
# Adatta il numero/ordine se il tuo esercito e' diverso.
TROOP_BAR_Y = 975
TROOP_SLOTS = [215, 340, 515]
HERO_SLOTS = [655, 785, 915, 1045]

# Zona di schieramento: tutte le truppe vengono piazzate qui, in un unico
# passaggio (lato destro/basso della base, quello testato con successo:
# 93% danno, 2 stelle). Non spostare truppe in zone diverse ad ogni run.
DEPLOY_POINTS = [
    (1300, 550), (1350, 500), (1400, 450), (1450, 400), (1500, 350), (1550, 300),
    (1400, 600), (1350, 650), (1300, 700), (1250, 720), (1200, 740),
    (1150, 760), (1100, 780), (1050, 800), (1000, 820),
]
TAPS_PER_TROOP = 10  # oltre alle truppe disponibili i tap in eccesso non fanno nulla
HERO_DEPLOY_POINT = (1350, 550)

THRESHOLD = 800000          # elisir minimo saccheggiabile per attaccare
MAX_SKIP_ATTEMPTS = 15       # avversari da scartare al massimo prima di attaccare comunque
CLICK_INTERVAL = 0.15
BATTLE_START_MAX_WAIT = 35.0   # attesa massima che la battaglia inizi dopo l'accettazione
BATTLE_DURATION_WAIT = (75.0, 100.0)  # attesa (min, max) per lasciare svolgere la battaglia

SESSION_DURATION = 50 * 60   # 50 minuti
MAX_TRIGGERS = 20            # numero di attacchi dopo cui il bot si ferma da solo
trigger_count = 0


# ==========================
# FUNZIONI
# ==========================

def read_available_loot():
    """Legge il valore di 'Bottino disponibile' (elisir) nella schermata di
    scouting. Il testo del gioco e' bianco con bordo nero su uno sfondo
    fotografico molto rumoroso: invece di un semplice threshold in scala di
    grigi, isoliamo i pixel bianchi in HSV (bassa saturazione, alta
    luminosita'), che si e' rivelato molto piu' affidabile nei test dal vivo.
    """
    frame = adb_screenshot()
    l, t = OCR_REGION["left"], OCR_REGION["top"]
    w, h = OCR_REGION["width"], OCR_REGION["height"]
    crop = frame[t:t + h, l:l + w]

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    lower = np.array([0, 0, 180])
    upper = np.array([180, 60, 255])
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.resize(mask, None, fx=5.0, fy=5.0, interpolation=cv2.INTER_CUBIC)
    mask = cv2.copyMakeBorder(mask, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=0)

    cv2.imwrite("debug.png", mask)

    ocr_config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(mask, config=ocr_config)

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def deploy_army():
    """Schiera TUTTE le truppe e gli eroi in un unico passaggio, sempre
    nella stessa zona (lato destro/basso della base) invece di sperimentare
    posizioni diverse ad ogni attacco.
    """
    print("[DEPLOY] Schiero le truppe...")
    for slot_x in TROOP_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(0.15)
        for (dx, dy) in DEPLOY_POINTS[:TAPS_PER_TROOP]:
            adb_tap(dx, dy)
            time.sleep(CLICK_INTERVAL)

    print("[DEPLOY] Schiero gli eroi...")
    for slot_x in HERO_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(0.15)
        adb_tap(*HERO_DEPLOY_POINT)
        time.sleep(CLICK_INTERVAL)

    time.sleep(2.0)

    print("[DEPLOY] Attivo le abilità eroi...")
    for slot_x in HERO_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(0.2)


def find_and_evaluate_opponent():
    """Cerca un avversario e valuta il bottino disponibile: scarta i
    bersagli sotto soglia (tasto 'Avanti') finché non ne trova uno buono o
    esaurisce i tentativi. Ritorna True se conviene attaccare.
    """
    for attempt in range(1, MAX_SKIP_ATTEMPTS + 1):
        time.sleep(0.8)
        loot = read_available_loot()
        print(f"[SCOUT] Tentativo {attempt}/{MAX_SKIP_ATTEMPTS} - elisir disponibile: {loot}")

        if loot is not None and loot >= THRESHOLD:
            print(f"[SCOUT] {loot} >= {THRESHOLD} -> attacco questa base")
            return True

        print("[SCOUT] Sotto soglia (o non letto) -> cerco un altro avversario")
        adb_tap(*SKIP_BUTTON)
        time.sleep(1.2)

    print("[SCOUT] Raggiunto il limite di tentativi, attacco comunque l'ultima base trovata.")
    return True


def wait_for_battle_start(max_wait=BATTLE_START_MAX_WAIT):
    """Aspetta che la battaglia inizi davvero: la schermata di scouting
    (con 'Bottino disponibile') sparisce quando parte il countdown finale.
    """
    print("[WAIT] Aspetto l'inizio della battaglia...")
    start = time.time()
    while time.time() - start < max_wait:
        if read_available_loot() is None:
            time.sleep(1.5)  # margine di sicurezza
            return True
        time.sleep(1.0)
    return False


def run_attack():
    """Un ciclo completo: cerca avversario, valuta, attacca, aspetta la
    fine della battaglia, torna al villaggio.
    """
    adb_tap(*ATTACK_BUTTON)
    time.sleep(1.5)
    adb_tap(*FIND_MATCH_BUTTON)
    time.sleep(2.0)
    adb_tap(*CONFIRM_ATTACK_BUTTON)
    time.sleep(3.0)

    find_and_evaluate_opponent()
    wait_for_battle_start()

    deploy_army()

    wait_time = random.uniform(*BATTLE_DURATION_WAIT)
    print(f"[WAIT] Lascio svolgere la battaglia (~{wait_time:.0f}s)...")
    time.sleep(wait_time)

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
    global trigger_count

    print("=== OCR BOT (ADB / BlueStacks) ===")
    print("debug.png viene aggiornato ad ogni lettura OCR del bottino")
    print("Ctrl + C per interrompere.\n")

    start_time = time.time()
    send_telegram(f"▶️ Bot avviato. Farà al massimo {MAX_TRIGGERS} attacchi o {int(SESSION_DURATION/60)} minuti.")

    while True:
        now = time.time()

        if now - start_time > SESSION_DURATION:
            msg = "Sono passati 50 minuti, fermo il bot per timeout."
            print(f"\n[STOP] {msg}")
            send_telegram(f"⏱ {msg} Attacchi totali: {trigger_count}")
            break

        trigger_count += 1
        print(f"\n[ATTACCO {trigger_count}/{MAX_TRIGGERS}]")

        try:
            run_attack()
        except Exception as e:
            print(f"[ERRORE] {e}")
            send_telegram(f"⚠️ Errore durante l'attacco {trigger_count}: {e}")
            time.sleep(5.0)
            continue

        if trigger_count >= MAX_TRIGGERS:
            msg = f"✅ Bot ha finito di farmare. Raggiunti {MAX_TRIGGERS} attacchi."
            print(f"[STOP] {msg}")
            send_telegram(msg)
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
    finally:
        # In esecuzione interattiva (terminale) aspetta un INVIO prima di
        # chiudere la finestra. In background (nohup/launchd, stdin non
        # collegato a un terminale) salta l'attesa: altrimenti il processo
        # resterebbe bloccato per sempre in attesa di input che non arriva.
        if sys.stdin.isatty():
            input("Script terminato. Premi INVIO per chiudere la finestra...")