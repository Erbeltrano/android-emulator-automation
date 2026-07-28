import pyautogui
import time
import random
import threading

CLICK_PAUSE = 0.2
ITERATIONS = 20

SEQ4_POINTS = [
    (486, 1300),
    (686, 1300),
    (886, 1300),
    (1086, 1300),
    (1286, 1300),
    (1486, 1300),
]

FIXED_POINT = (252, 1267)

RACCOLTA_POINTS = [
    (1657, 104),
    (1878, 1211),
    (175, 1219),
]

def click_point(x, y, pause=CLICK_PAUSE):
    pyautogui.click(x, y)
    time.sleep(pause)

def hold_key(key='down', hold_sec=1.5, times=1, gap_sec=0.2):
    for _ in range(times):
        pyautogui.keyDown(key)
        time.sleep(hold_sec)
        pyautogui.keyUp(key)
        time.sleep(gap_sec)

def fixed_clicks_background(point, clicks=3, interval_sec=18, stop_event=None):
    fx, fy = point
    for n in range(1, clicks + 1):

        if stop_event and stop_event.is_set():
            return

        print(f"🎯 (bg) Click fisso {n}/{clicks}")
        pyautogui.click(fx, fy)

        end_time = time.time() + interval_sec

        while time.time() < end_time:
            if stop_event and stop_event.is_set():
                return
            time.sleep(0.1)

def sequenza_raccolta(points):

    print("🧺 SEQUENZA RACCOLTA attiva")

    for idx, (x, y) in enumerate(points, start=1):
        print(f"🧺 Raccolta click {idx}/{len(points)}")
        click_point(x, y)


print("✅ Script avviato. Premi CTRL + C per uscire.")

stop_event = threading.Event()

try:

    for i in range(1, ITERATIONS + 1):

        print(f"\n🔁 Giro {i}/{ITERATIONS}")

        time.sleep(4)

        # --- FOCUS FINESTRA ---
        pyautogui.click(252, 1267)
        time.sleep(0.2)

        # --- DEZOOM ---
        hold_key('down', hold_sec=1.5)

        # --- SEQUENZA 1 ---
        print("▶ SEQUENZA 1")

        click_point(252, 1267)
        click_point(2198, 746)
        click_point(481, 1267)

        for _ in range(6):
            click_point(2198, 746)

        # --- BACKGROUND CLICKS ---
        t = threading.Thread(
            target=fixed_clicks_background,
            args=(FIXED_POINT, 3, 8, stop_event),
            daemon=True
        )
        t.start()

        # --- ATTESA PRIMA SEQUENZA 4 ---
        time.sleep(10)

        # --- SEQUENZA 4 ---
        print("🏘️ SEQUENZA 4")

        for (x, y) in SEQ4_POINTS:
            click_point(x, y)

        # --- ATTESA 60s ---
        print("⏳ Attesa 60 secondi prima della SEQUENZA 5")
        time.sleep(60)

        # --- SEQUENZA 5 (COPIA SEQUENZA 1) ---
        print("🏘️ SEQUENZA 5 - Secondo Villaggio")

        click_point(252, 1267)
        click_point(2198, 746)
        click_point(481, 1267)

        for _ in range(8):
            click_point(2198, 746)

        t = threading.Thread(
            target=fixed_clicks_background,
            args=(FIXED_POINT, 3, 8, stop_event),
            daemon=True
        )
        t.start()

        # --- ATTESA VARIABILE ---
        wait_time = random.uniform(32, 45)

        print(f"⏳ Attesa variabile: {wait_time:.1f}s")
        time.sleep(wait_time)

        # --- SEQUENZA 2 ---
        print("▶ SEQUENZA 2")

        time.sleep(2)
        click_point(174, 1000)
        click_point(1547, 921)
        click_point(1264, 1217)

        # --- RACCOLTA SOLO AL 10° GIRO ---
        if i == 10:

            print("⏸ Attesa 4 secondi prima della SEQUENZA RACCOLTA")
            time.sleep(4)
            sequenza_raccolta(RACCOLTA_POINTS)

        # --- ATTESA PRIMA SEQUENZA 3 ---
        time.sleep(2)

        # --- SEQUENZA 3 ---
        print("▶ SEQUENZA 3")

        click_point(175, 1219)
        click_point(1891, 934)

    print("\n✅ Completato: 20/20 giri finiti.")

except KeyboardInterrupt:

    stop_event.set()
    print("\n👋 Interrotto dall’utente con CTRL + C")