import os
import sys
import time
import random
import shutil
import platform
import mss
import numpy as np
import cv2
import pytesseract
import pyautogui
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
    """Trova l'eseguibile di Tesseract sia su Windows che su macOS."""
    # 1) Se è già nel PATH (tipico su Mac con Homebrew), usa quello
    found = shutil.which("tesseract")
    if found:
        return found

    # 2) Percorsi comuni in base al sistema operativo
    system = platform.system()
    if system == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    else:  # macOS / Linux
        candidates = [
            "/opt/homebrew/bin/tesseract",   # Homebrew su Apple Silicon (M1/M2/M3)
            "/usr/local/bin/tesseract",      # Homebrew su Mac Intel
            "/usr/bin/tesseract",
        ]

    for path in candidates:
        if shutil.os.path.exists(path):
            return path

    raise FileNotFoundError(
        "Tesseract non trovato. Su Mac installalo con: brew install tesseract\n"
        "Poi verifica il percorso con: which tesseract"
    )


pytesseract.pytesseract.tesseract_cmd = find_tesseract_cmd()
pyautogui.FAILSAFE = True

# --- REGIONE OCR CORRETTA (calibrata manualmente sul Mac, allargata per numeri >1 milione) ---
OCR_REGION = {
    "left": 78,
    "top": 157,
    "width": 150,
    "height": 30
}

# --- PRIMA SEQUENZA DI CLICK (scalata per Mac 1440x900, originale Windows 2560x1440) ---
CLICK_SEQUENCE = [
    (180, 804),   # 1 --- 360 primo slot- 
    (762, 699),  # 2
    (843,  623),  # 3
    (949,  556),  # 4
    (1031,  488),  # 5
    (1106,  421),  # 6
    (1158,  379),  # 7
    (1213,  332),  # 8
    (1284,  257),  # 9
    (1031,  488),  # 5
    (1031,  488),  # 5
    (259, 804),   # 1 --- 460 secondo slot- 
    (762, 699),  # 2
    (843,  623),  # 3
    (949,  556),  # 4
    (1031,  488),  # 5
    (1106,  421),  # 6
    (1158,  379),  # 7
    (1213,  332),  # 8
    (1284,  257),  # 9
    (1031,  488),  # 5
    (1031,  488),  # 5
    (504,  720),  # 10 - 896 selezione regina
    (1036,  492),  # 11 - posizione regina
    (504,  720),  # 10 - abilità regina
    (618, 720),  # 12
    (1032,  495),  # 13
    (729,  750),  # 14 - gran sorvegliante
    (1036,  492),  # 15 - posizione gran sorvegliante
    (842,  740),  # 14 - gran sorvegliante
    (1036,  492),  # 15 - posizione gran sorvegliante
    (842,  740),  # 14 - gran sorvegliante
    (923,  340),  # 15 - posizione gran sorvegliante
    (805,  439),  # 15 - posizione gran sorvegliante
   
	
]

# --- SECONDA SEQUENZA DI CLICK (scalata per Mac) ---
SECOND_CLICK_SEQUENCE = [
    (105, 673),   # A
    (870, 591),   # B
    (713, 769),  # C
    (98, 779),  # D
    (214, 669),  # E
    (1227, 803),  # F
]

# --- TERZA SEQUENZA DI CLICK (scalata per Mac, T3 ricalibrato manualmente) ---
THIRD_CLICK_SEQUENCE = [
    (92, 789),   # T1
    (216, 667),  # T2
    (1275, 768),  # T3 - ricalibrato: riattiva attacco
]

# --- PUNTO DA CLICCARE QUANDO value < THRESHOLD (scalato per Mac) ---
LOW_VALUE_POINT = (1307, 641)

# --- PUNTO DA CLICCARE QUANDO NON LEGGE NUMERI PER TROPPO TEMPO (scalato per Mac) ---
NO_NUMBER_CLICK_POINT = (105, 673)  # come richiesto

THRESHOLD = 800000
POLL_INTERVAL = 0.7
CLICK_INTERVAL = 0.20
TRIGGER_COOLDOWN = 3.0
THIRD_CLICK_INTERVAL = 0.5   # terza sequenza più lenta

NO_NUMBER_TIMEOUT = 80.0     # secondi senza numero prima di reagire
SESSION_DURATION = 50 * 60   # 50 minuti

# --- SCROLL TRAMITE DRAG (scalato per Mac) ---
DRAG_START = (563, 500)  # punto di partenza del drag
DRAG_END   = (563, 250)  # punto finale del drag
DRAG_DURATION = 0.6       # durata del drag

# --- CONTATORE DEI TRIGGER SOPRA SOGLIA ---
trigger_count = 0
MAX_TRIGGERS = 20


# ==========================
# FUNZIONI
# ==========================

def read_number_from_dashboard():
    with mss.MSS() as sct:
        sct_img = sct.grab(OCR_REGION)
        frame = np.array(sct_img)

    # 1) Scala di grigi
    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

    # 2) Ingrandisci un po' il testo (aiuta Tesseract)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)

    # 3) Leggero blur per togliere rumore
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # 4) Threshold automatico (Otsu)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Debug
    cv2.imwrite("debug.png", thresh)

    # 5) Config OCR: solo numeri, psm 7 (una sola riga)
    ocr_config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(thresh, config=ocr_config)

    digits = "".join(ch for ch in text if ch.isdigit())

    if not digits:
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def scroll_down_by_drag():
    """Simula uno scroll trascinando il mouse."""
    print("[ACTION] Scroll tramite drag...")
    pyautogui.moveTo(DRAG_START[0], DRAG_START[1])
    time.sleep(0.2)
    pyautogui.dragTo(DRAG_END[0], DRAG_END[1], duration=DRAG_DURATION, button='left')
    time.sleep(2.0)  # pausa dopo lo scroll


def execute_click_sequence_full():
    """Sequenza completa: scroll + prima + seconda + (attesa) + terza."""
    scroll_down_by_drag()

    print("[ACTION] Eseguo PRIMA sequenza di click...")
    for i, (x, y) in enumerate(CLICK_SEQUENCE, start=1):
        print(f"  -> Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(CLICK_INTERVAL)
    print("[ACTION] Prima sequenza completata.")

    wait_time = random.uniform(50, 70)
    print(f"[WAIT] Attendo circa {wait_time:.1f} secondi prima della SECONDA sequenza...")
    time.sleep(wait_time)

    print("[ACTION] Eseguo SECONDA sequenza di click...")
    for i, (x, y) in enumerate(SECOND_CLICK_SEQUENCE, start=1):
        print(f"  -> Seconda seq - Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(CLICK_INTERVAL)
    print("[ACTION] Seconda sequenza completata.")

    time.sleep(3)

    print("[ACTION] Eseguo TERZA sequenza di click...")
    for i, (x, y) in enumerate(THIRD_CLICK_SEQUENCE, start=1):
        print(f"  -> Terza seq - Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(THIRD_CLICK_INTERVAL)
    print("[ACTION] Terza sequenza completata.")


def execute_click_sequence_without_third():
    """Sequenza finale: scroll + prima + seconda (senza terza)."""
    scroll_down_by_drag()

    print("[ACTION] (FINALE) Eseguo PRIMA sequenza di click...")
    for i, (x, y) in enumerate(CLICK_SEQUENCE, start=1):
        print(f"  -> Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(CLICK_INTERVAL)
    print("[ACTION] (FINALE) Prima sequenza completata.")

    wait_time = random.uniform(50, 70)
    print(f"[WAIT] (FINALE) Attendo circa {wait_time:.1f} secondi prima della SECONDA sequenza...")
    time.sleep(wait_time)

    print("[ACTION] (FINALE) Eseguo SECONDA sequenza di click...")
    for i, (x, y) in enumerate(SECOND_CLICK_SEQUENCE, start=1):
        print(f"  -> Seconda seq FINALE - Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(CLICK_INTERVAL)
    print("[ACTION] (FINALE) Seconda sequenza completata (NESSUNA TERZA).")


def execute_second_and_third_sequence():
    """(NON PIÙ USATA, ma la lascio se ti serve in futuro)."""
    print("[NO-NUMBER] Nessun numero letto da tempo -> SECONDA + TERZA sequenza")

    print("[ACTION] (NO-NUMBER) Eseguo SECONDA sequenza di click...")
    for i, (x, y) in enumerate(SECOND_CLICK_SEQUENCE, start=1):
        print(f"  -> Seconda seq (no-number) - Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(CLICK_INTERVAL)
    print("[ACTION] (NO-NUMBER) Seconda sequenza completata.")

    time.sleep(3)

    print("[ACTION] (NO-NUMBER) Eseguo TERZA sequenza di click...")
    for i, (x, y) in enumerate(THIRD_CLICK_SEQUENCE, start=1):
        print(f"  -> Terza seq (no-number) - Click {i} su ({x}, {y})")
        pyautogui.click(x=x, y=y)
        time.sleep(THIRD_CLICK_INTERVAL)
    print("[ACTION] (NO-NUMBER) Terza sequenza completata.")


def click_no_number_point_and_third():
    """Quando non leggiamo numeri per NO_NUMBER_TIMEOUT:
       1) clicca un punto specifico
       2) esegue SOLO la TERZA sequenza.
    """
    x, y = NO_NUMBER_CLICK_POINT
    print(f"[NO-NUMBER] Nessun numero da tanto -> clicco punto speciale ({x}, {y})")
    pyautogui.click(x=x, y=y)
    time.sleep(1.0)

    print("[NO-NUMBER] Eseguo SOLO TERZA sequenza di click...")
    for i, (cx, cy) in enumerate(THIRD_CLICK_SEQUENCE, start=1):
        print(f"  -> Terza seq (no-number) - Click {i} su ({cx}, {cy})")
        pyautogui.click(x=cx, y=cy)
        time.sleep(THIRD_CLICK_INTERVAL)
    print("[NO-NUMBER] Terza sequenza completata.")


def click_low_value_point():
    """Quando il valore è < THRESHOLD: aspetta 3s e clicca un solo punto."""
    x, y = LOW_VALUE_POINT
    print(f"[LOW] Valore sotto soglia, attendo 3 secondi e clicco su ({x}, {y})")
    time.sleep(3.0)
    pyautogui.click(x=x, y=y)


def calibrate_coordinates():
    """
    Helper di calibrazione: muovi il mouse sui punti che ti servono e
    lo script stampa in tempo reale le coordinate (x, y) sotto il cursore.
    Utile perché le coordinate salvate nello script erano calibrate sul
    PC Windows e sul Mac saranno quasi certamente diverse (risoluzione /
    scaling Retina differenti).

    Per usarlo: lancia lo script con  python BOT_COMPLETO_MAC.py --calibrate
    Premi Ctrl+C per uscire quando hai finito.
    """
    print("=== MODALITÀ CALIBRAZIONE ===")
    print("Muovi il mouse sui punti di interesse. Ctrl+C per uscire.\n")
    try:
        while True:
            x, y = pyautogui.position()
            print(f"\rPosizione mouse: ({x}, {y})   ", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nCalibrazione terminata.")


def main():
    global trigger_count

    print("=== OCR BOT ===")
    print("debug.png viene aggiornato ad ogni lettura")
    print("Ctrl + C per interrompere.\n")

    last_trigger_time = 0
    start_time = time.time()
    last_number_seen_time = time.time()   # timer "no-number"

    while True:
        now = time.time()

        # STOP dopo SESSION_DURATION
        if now - start_time > SESSION_DURATION:
            msg = "Sono passati 50 minuti, fermo il bot per timeout."
            print(f"\n[STOP] {msg}")
            send_telegram(f"⏱ {msg} Trigger totali: {trigger_count}")
            break

        value = read_number_from_dashboard()

        if value is not None:
            print("Valore letto:", value)
            # RESET TIMER ogni volta che leggiamo un numero valido
            last_number_seen_time = now

            # CASO 1 — valore sopra soglia
            if value > THRESHOLD and (now - last_trigger_time) > TRIGGER_COOLDOWN:
                trigger_count += 1
                print(f"[TRIGGER-HIGH] {value} > {THRESHOLD} -> trigger n° {trigger_count}/{MAX_TRIGGERS}")

                if trigger_count < MAX_TRIGGERS:
                    print("[MODE] Sequenza completa (1 + 2 + 3)")
                    execute_click_sequence_full()
                    last_number_seen_time = time.time()

                elif trigger_count == MAX_TRIGGERS:
                    print("[MODE] TRIGGER FINALE: solo prima + seconda, poi stop.")
                    execute_click_sequence_without_third()

                    msg = f"✅ Bot ha finito di farmare. Raggiunti {MAX_TRIGGERS} trigger sopra soglia."
                    print(f"[STOP] {msg}")
                    send_telegram(msg)
                    break

                last_trigger_time = time.time()
                continue

            # CASO 2 — valore sotto soglia
            elif value < THRESHOLD:
                click_low_value_point()
                last_number_seen_time = time.time()

        else:
            print("Non ho letto nessun numero")

            # se NON leggiamo numeri per più di NO_NUMBER_TIMEOUT secondi
            if now - last_number_seen_time > NO_NUMBER_TIMEOUT:
                print(f"[NO-NUMBER] Nessun numero da {NO_NUMBER_TIMEOUT} secondi, clic punto speciale + TERZA")
                click_no_number_point_and_third()
                last_number_seen_time = time.time()

        time.sleep(POLL_INTERVAL)


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
        input("Script terminato. Premi INVIO per chiudere la finestra...")