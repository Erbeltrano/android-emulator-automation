import os
import sys
import json
import time
import random
import re
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

# bot_log.txt non aveva alcun orario, solo l'ordine delle righe: per
# diagnosticare un incidente da remoto (es. via SSH mentre l'utente è
# fuori) bisognava dedurre i tempi a occhio o riprodurre dal vivo. Ogni
# print del bot passa comunque da qui, quindi basta un solo punto per
# aggiungere l'orario a tutte le righe senza toccare le centinaia di
# chiamate a print() sparse nel file (v3.15).
_builtin_print = print


def print(*args, **kwargs):
    _builtin_print(f"[{time.strftime('%H:%M:%S')}]", *args, **kwargs)


# Aggiornare ad ogni modifica funzionale del bot (anche nel README).
VERSION = "3.16"

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


def send_telegram_photo(path: str, caption: str = ""):
    """Manda una foto (screenshot) al chat_id, con una didascalia opzionale.

    v3.14: usato quando il bot si arrende su un ciclo per un problema a
    schermo (es. popup imprevisto che blocca 'Attacco!') - prima l'utente
    doveva chiedere uno screenshot a parte via Telegram per capire cosa
    stesse succedendo davvero (scoperto dal vivo il 2026-08-10: senza
    vedere lo schermo, un messaggio di solo testo puo' sembrare in
    contraddizione con quel che si vede aprendo un altro screenshot preso
    in un momento diverso). Allegarlo subito nello stesso messaggio evita
    quell'ambiguita'.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                files={"photo": f},
                timeout=20,
            )
        print("[TELEGRAM] sendPhoto status:", resp.status_code)
    except Exception as e:
        print("[TELEGRAM] Errore invio foto:", e)

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


def adb_screenshot(retries=3, retry_delay=1.0):
    """Cattura lo schermo dell'emulatore e ritorna un array numpy BGR (OpenCV).

    Ritenta in caso di fallimento: subito dopo un avvio a freddo (sveglia
    via Wake-on-LAN + BlueStacks appena lanciato) il primo screencap puo'
    fallire anche se ADB vede gia' il device "device" pronto (visto dal
    vivo: CalledProcessError con exit status -1). Prima non c'era nessun
    ritentativo, quindi un singolo hiccup faceva crashare l'intera sessione.

    Cattura anche cv2.error: uno screencap che torna 0 byte (altro sintomo
    dello stesso hiccup post-risveglio, visto dal vivo il 27/07) fa fallire
    cv2.imdecode con un'assertion invece di ritornare un frame None -
    prima bypassava questo stesso retry pensato apposta per quel caso.

    Se anche questi retry ravvicinati falliscono tutti, prova _adb_recover()
    (v3.15) prima di arrendersi - stesso bridge ADB di adb_tap/adb_swipe,
    stesso rischio di blocco piu' lungo di un semplice hiccup.
    """
    def _capture_once():
        result = adb("exec-out", "screencap", "-p", device=DEVICE)
        img_array = np.frombuffer(result.stdout, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Screenshot ADB non decodificabile (screencap fallito?).")
        return frame

    last_error = None
    for attempt in range(retries):
        try:
            return _capture_once()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, cv2.error) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(retry_delay)

    if _adb_recover():
        try:
            return _capture_once()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, cv2.error) as e:
            last_error = e

    raise last_error


def _adb_recover(max_wait=20.0, poll_interval=1.5):
    """Prova a far ripartire l'adb server e ritrova il device, riassegnando
    DEVICE se il serial e' cambiato.

    Trovato dal vivo il 2026-08-12: il bridge adb di BlueStacks puo'
    bloccarsi per diversi secondi (osservato esattamente al primo swipe
    dopo l'inizio della battaglia, cioe' durante il caricamento pesante
    della base avversaria) e restare rotto per piu' a lungo di quanto i
    pochi retry ravvicinati di _adb_retry riescano a coprire (visti falliti
    3 attacchi di fila, quindi ben oltre qualche secondo). Un "adb devices"
    innocuo (fa ripartire da solo il server se e' morto, come osservato
    manualmente) e' spesso sufficiente; kill-server e' li' solo come rete
    di sicurezza se il client non lo rileva da solo.
    """
    global DEVICE
    try:
        subprocess.run([ADB_CMD, "kill-server"], capture_output=True, timeout=10)
    except Exception:
        pass
    waited = 0.0
    while waited < max_wait:
        try:
            result = adb("devices")
            lines = result.stdout.decode(errors="ignore").strip().splitlines()[1:]
            for line in lines:
                if line.strip().endswith("device"):
                    DEVICE = line.split()[0]
                    return True
        except Exception:
            pass
        time.sleep(poll_interval)
        waited += poll_interval
    return False


def _adb_retry(func, retries=3, retry_delay=1.0):
    """Ritenta una chiamata adb (tap/swipe) in caso di intoppo transitorio -
    stesso tipo di hiccup post-risveglio gia' visto e gestito per lo
    screenshot (adb_screenshot), ma prima non coperto qui: un singolo
    fallimento di un tap/swipe contava subito come un errore verso il
    limite di errori consecutivi della sessione (osservato dal vivo il
    27/07: 4 sessioni di fila interrotte da singoli intoppi ADB transitori
    sul tap di "Attacco!", subito dopo un risveglio via Wake-on-LAN).

    Se anche questi retry ravvicinati falliscono tutti, prova UNA volta
    _adb_recover() (vedi sopra) prima di arrendersi definitivamente: copre
    il caso di un blocco piu' lungo del bridge adb invece del semplice
    hiccup di un istante.
    """
    last_error = None
    for attempt in range(retries):
        try:
            return func()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(retry_delay)

    if _adb_recover():
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
    _adb_retry(lambda: adb(
        "shell", "input", "swipe",
        str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        device=DEVICE,
    ))


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

# "Danno complessivo N%" durante la battaglia (basso a destra), calibrata
# dal vivo su screenshot reali sia con "2%" che con "36%" (il testo è
# allineato a destra, quindi una regione larga copre anche "100%"). Usata
# in v3.1 per capire quando le truppe sono morte/ferme invece di aspettare
# sempre un tempo fisso a schermo vuoto (vedi wait_for_battle_end()).
OCR_REGION_DAMAGE = {
    "left": 1650,
    "top": 775,
    "width": 270,
    "height": 60,
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

# Capacita' massima dei depositi (v2.0, sessioni a durata dinamica invece di
# un numero fisso di attacchi): toccare la barra oro/elisir apre un tooltip
# con "Max: N / Produzione oraria: N / In tesoreria: N" - letta dal vivo il
# 2026-07-25. Si legge da li' invece di un valore fisso perche' cambia ogni
# volta che si potenzia un deposito. Il tap sullo stesso punto e' un toggle
# (secondo tap = chiude), scoperto durante i test dell'upgrade mura.
GOLD_BAR_POINT = (1750, 65)
ELIXIR_BAR_POINT = (1750, 165)
STORAGE_MAX_TOOLTIP_REGION = {
    "left": 1425, "top": 90, "width": 495, "height": 200,
}
STORAGE_FULL_THRESHOLD = 0.92  # oltre questa percentuale della capacita' un deposito e' considerato "pieno"
STORAGE_LOW_RATIO = 0.5  # sotto questa percentuale della propria capacita' massima, oro/elisir sono
                          # ancora "scarsi" - non ci si ferma solo perche' l'altra valuta e' gia' piena
                          # (v3.13, vedi storage_is_full)

# v3.14 (2026-08-10): bug vero trovato dal vivo - l'utente ha segnalato
# oro/elisir pieni ed elisir nero VUOTO, ma il bot si e' fermato comunque
# ("depositi quasi pieni"). La protezione per l'elisir nero esisteva già
# (v3.7/v3.11, vedi storage_is_full) ma si basava su una soglia ASSOLUTA
# fissa (home_low_dark_elixir, 400.000) invece che sulla vera capacita' del
# deposito - la stessa classe di bug gia' fixata per oro/elisir il
# 2026-08-09 (v3.13), mai estesa all'elisir nero. Verificato dal vivo oggi
# (screenshot reale, tooltip aperto sulla barra elisir nero): la capacita'
# vera del deposito e' 430.000, e l'elisir nero in casa in quel momento era
# 38.995 (9%, genuinamente "vuoto") - una soglia assoluta di 400.000 (93%
# di QUESTA capacita' specifica) puo' sembrare quasi corretta per caso ora,
# ma smette di funzionare appena il deposito viene potenziato ulteriormente
# (esattamente il motivo per cui oro/elisir leggono la capacita' dal vivo
# invece di un numero fisso). Inoltre una soglia assoluta e' vulnerabile a
# letture OCR "fantasma" (cifra in piu' letta per errore, bug gia' noto e
# documentato altrove in questo file): con una soglia proporzionale, il
# controllo di sanita' gia' esistente (il massimo non puo' essere inferiore
# a quanto c'e' in casa) scarta automaticamente anche queste letture
# impossibili, cosa che una soglia assoluta non poteva fare.
#
# Fix: stessa tecnica di oro/elisir - tooltip "Max" letto dal vivo toccando
# la barra elisir nero, "pieno" = sopra STORAGE_FULL_THRESHOLD della vera
# capacita' (non piu' home_low_dark_elixir, lasciato in config solo per
# compatibilita' con determine_priority_resource() che lo usa per un scopo
# diverso, a inizio sessione, quando la capacita' vera non serve leggerla).
DARK_ELIXIR_BAR_POINT = (1750, 265)
DARK_ELIXIR_MAX_TOOLTIP_REGION = {
    "left": 1425, "top": 290, "width": 495, "height": 200,
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
# passaggio. Ricalibrati il 2026-07-28 col "metodo della griglia" (overlay
# a celle 160px su uno screenshot di battaglia reale, con conferma dal vivo
# del bug: "Non puoi schierare truppe nella zona rossa" e solo 2% di danno
# con la vecchia lista sparsa). L'utente ha indicato a mano, disegnando
# sull'overlay, la diagonale del bordo esterno valido per QUELLA base
# (da cella K1 a cella G5, cioe' pixel (1736,300)->(1104,864)): questi 18
# punti sono equispaziati lungo quella diagonale. Sostituiscono per intero
# il vecchio pool sparso (due diagonali diverse + punti aggiunti alla
# cieca) su richiesta esplicita dell'utente, per non diluire nello shuffle
# casuale l'effetto della calibrazione precisa appena fatta. Se emergono
# basi dove questa diagonola non basta, ripetere il metodo della griglia
# invece di aggiungere punti a caso.
DEPLOY_POINTS = [
    (1736, 300), (1699, 333), (1662, 366), (1625, 400), (1587, 433), (1550, 466),
    (1513, 499), (1476, 532), (1439, 565), (1401, 599), (1364, 632), (1327, 665),
    (1290, 698), (1253, 731), (1216, 765), (1178, 798), (1141, 831), (1104, 864),
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
DRAG_DURATION = 0.45

# Pulsante rosso "Termina battaglia" / "Resa" (stessa posizione, testo
# diverso a seconda che tu abbia gia' schierato truppe o no). Se hai gia'
# schierato truppe, il gioco chiede conferma con un popup "Arrendersi?"
# (Annulla/OK): il pulsante OK verde e' a CONFIRM_END_BATTLE_BUTTON.
END_BATTLE_BUTTON = (140, 785)
CONFIRM_END_BATTLE_BUTTON = (1150, 670)

# Upgrade mura (v2.0, flag "auto_wall_upgrade"): a fine sessione, se c'e'
# un costruttore libero, mette in coda l'upgrade di quante piu' mura
# possibile con le risorse rimaste in casa. Le mura non richiedono tempo
# di costruzione (acquisto istantaneo con oro o elisir): "costruttore
# libero" qui e' solo il segnale scelto dall'utente per capire se e' un
# buon momento per investire in progressione invece di continuare a
# farmare soltanto. Coordinate calibrate dal vivo (screenshot 1920x1080)
# il 2026-07-23/24; la posizione del badge costruttori in alto e' emersa
# stabile nei test dal vivo (l'utente conferma che non si sposta).
BUILDER_BADGE_POINT = (955, 65)           # icona/badge "liberi/totali" in alto
BUILDER_BADGE_REGION = {                   # ritaglio stretto sulla sola cifra "liberi"
    "left": 938, "top": 38, "width": 40, "height": 52,
}
WALL_DROPDOWN_REGION = {                   # area del menu a tendina "Miglioramenti"
    "left": 630, "top": 150, "width": 700, "height": 720,
}
WALL_DROPDOWN_SCROLL = ((975, 700), (975, 300))  # swipe per scorrere la lista in cerca di "Muro"
WALL_ACTION_BAR_REGION = {                 # barra pulsanti in basso dopo aver selezionato un muro
    "left": 300, "top": 760, "width": 1350, "height": 160,
}
GENERIC_DIALOG_OK_POINT = (1180, 693)      # pulsante "OK" dei popup di conferma generici del
                                            # gioco (es. "Migliora le mura?", "Terminare
                                            # battaglia?"): stessa posizione fissa per entrambi,
                                            # verificato dal vivo, non serve rilevarlo dinamicamente
DESELECT_POINT = (1750, 65)                # barra dell'oro in alto a destra: elemento UI fisso
                                            # (non il mondo di gioco), utile per deselezionare
                                            # qualunque cosa con due tap sullo stesso punto. Un punto
                                            # "vuoto" sulla mappa NON e' mai davvero sicuro: la
                                            # telecamera si sposta selezionando dalla lista, quindi lo
                                            # stesso punto puo' cadere su decorazioni cliccabili o
                                            # perfino sulla barca per il villaggio costruttori
                                            # (scoperto dal vivo). Suggerito dall'utente: due tap sullo
                                            # stesso elemento UI fisso (qui la barra oro) deseleziona
                                            # in modo affidabile qualsiasi pannello/selezione aperta.


def deselect_all():
    """Chiude qualunque pannello/selezione aperta (menu upgrade, muro
    selezionato, ecc.) toccando due volte lo stesso punto della barra
    dell'oro in alto: un elemento di interfaccia fisso, non una coordinata
    sulla mappa di gioco (che si sposta con la telecamera ed e' quindi
    inaffidabile per questo scopo - vedi commento su DESELECT_POINT).
    """
    adb_tap(*DESELECT_POINT)
    time.sleep(0.6)
    adb_tap(*DESELECT_POINT)
    time.sleep(1.0)
WALL_MAX_SCROLL_ATTEMPTS = 6
WALL_MAX_ADD_TAPS = 60   # tetto di sicurezza sui tap "+1" (non dovrebbe mai servire arrivarci)

# Parametri di farming regolabili dalla dashboard web (sezione Impostazioni):
# letti da config.json accanto allo script, con questi valori come default
# se il file non c'e' o e' incompleto. Le soglie "threshold_*" sono il
# bottino minimo del bersaglio per attaccare (una per risorsa, usata solo
# quella della risorsa prioritaria della sessione); le "home_low_*" sono
# la soglia sotto la quale una risorsa in casa e' considerata scarsa (usate
# solo se priority_mode e' "auto"). "priority_mode" sceglie come decidere
# la risorsa prioritaria: "auto" (rileva da solo cosa scarseggia in casa,
# comportamento della v1.6) oppure forzata a "gold"/"elixir"/"dark_elixir"
# per saltare il rilevamento e attaccare sempre in base a quella, con la
# sua threshold_* configurata.
CONFIG_FILE = "config.json"
_CONFIG_DEFAULTS = {
    "priority_mode": "auto",
    "threshold_gold": 800000,
    "threshold_elixir": 800000,
    "threshold_dark_elixir": 3000,
    "home_low_gold": 300000,
    "home_low_elixir": 300000,
    "home_low_dark_elixir": 400000,
    "max_triggers": 20,
    "session_duration_minutes": 50,
    "auto_wall_upgrade": False,
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
CLICK_INTERVAL_RANGE = (0.08, 0.14)  # intervallo breve e variabile: accelera il deploy
                                      # senza togliere a BlueStacks il tempo di registrare ogni tap
BATTLE_START_MAX_WAIT = 4.0  # riportato a un'attesa breve il 2026-07-29 su richiesta esplicita
                               # dell'utente, dopo aver rivisto dal vivo la v2.9 (countdown pieno
                               # a 40s): secondo l'utente il piazzamento funziona comunque durante
                               # il countdown di matchmaking, il problema del 2026-07-28 (vedi
                               # storia sotto) sarebbe stato causato da altro, non dal countdown.
                               # CONFERMATO in produzione lo stesso giorno (utente presente
                               # davanti allo schermo, live): funziona "alla perfezione" con 4.0.
                               # La spiegazione "finestra morta del countdown" del 2026-07-28 era
                               # quindi sbagliata o incompleta (il vero fix di quel giorno era
                               # probabilmente la ricalibrazione di DEPLOY_POINTS in v2.9, non
                               # l'attesa lunga). Non ripristinare 30-40s per questo motivo.
                               #
                               # Storia (per contesto, non piu' la spiegazione accettata): era
                               # 2.0 fin dalla riscrittura ADB (commit b5bdf6b), portato a 30.0
                               # poi 40.0 il 2026-07-28 dopo aver osservato "2-3 truppe invece di
                               # 10"/0% danno con l'ipotesi che i tap di deploy cadessero in una
                               # finestra morta prima della fine reale del countdown.
BATTLE_DURATION_WAIT = (45.0, 120.0)  # v3.1: il minimo non e' piu' usato per un'attesa fissa
                                       # (vedi wait_for_battle_end() sotto), resta solo il
                                       # massimo come tetto di sicurezza se l'OCR del danno
                                       # smette di funzionare.

# v3.1: invece di aspettare sempre un tempo fisso/casuale a schermo fermo
# (l'utente ha notato dal vivo che spesso le truppe muoiono quasi subito e
# il bot resta a "fissare il vuoto" per un minuto o piu'), si legge la
# percentuale di "Danno complessivo" a intervalli regolari: se resta
# invariata per DAMAGE_STALL_SECONDS, le truppe sono verosimilmente morte o
# ferme (nessun altro danno in arrivo) e si termina subito, invece di
# aspettare il tetto massimo.
DAMAGE_POLL_INTERVAL = 2.0   # abbassato da 5.0 il 2026-07-29: con un controllo ogni 5s
                              # l'ultimo aumento rilevato poteva essere fino a 5s piu'
                              # vecchio di quando succedeva davvero, facendo scattare lo
                              # stallo prima di quanto sembrasse guardando lo schermo
DAMAGE_STALL_SECONDS = 25.0  # 15.0 -> 20.0 -> 25.0 il 2026-07-29: l'utente ha visto dal
                              # vivo la battaglia terminare in anticipo con truppe ancora
                              # vive (pause normali di combattimento - es. un P.E.K.K.A.
                              # che rosicchia un muro, un eroe che cammina tra un edificio
                              # e l'altro - possono far restare la % ferma per diversi
                              # secondi senza che le truppe siano morte)
DAMAGE_GRACE_PERIOD = 10.0   # subito dopo lo schieramento le truppe stanno ancora
                              # marciando verso la base: non giudicare uno stallo
                              # prima che sia passato questo tempo

SESSION_DURATION = _config["session_duration_minutes"] * 60
MAX_TRIGGERS = _config["max_triggers"]         # numero di attacchi dopo cui il bot si ferma da solo
trigger_count = 0

# Risorsa su cui la sessione e' concentrata (decisa da determine_priority_resource()
# in main(), prima del loop di attacco: quella piu' scarsa in casa rispetto
# alle soglie home_low_*, o "gold" di default se nessuna scarseggia).
priority_resource = "gold"

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

# Fase corrente della sessione, per far vedere alla dashboard cosa sta
# succedendo *durante* un attacco (prima si aggiornava solo a fine ciclo
# completo, quindi per 1-2 minuti a testa la dashboard restava ferma
# sull'attacco precedente anche a bot ben vivo). "scouting" include il
# dettaglio del tentativo corrente; None quando non c'e' scouting in corso.
current_phase = "idle"
scout_progress = None


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
                "session_totals": session_totals,
                "phase": current_phase,
                "scout_progress": scout_progress,
                "updated_at": time.time(),
            }, f)
    except Exception as e:
        print(f"[STATUS] Errore scrittura {STATUS_FILE}: {e}")


def format_totals_summary():
    """Riga di riepilogo del bottino stimato della sessione, per i
    messaggi Telegram di fine sessione."""
    t = session_totals
    return (
        f"Bottino stimato: 🥇{t['gold']:,} 🧪{t['elixir']:,} 🔮{t['dark_elixir']:,}"
        .replace(",", ".")
    )


def append_history_entry(end_reason="completata"):
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
        "end_reason": end_reason,
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
    l'altra (es. subito dopo aver toccato 'Avanti'). Funziona identico su
    entrambi i villaggi (verificato dal vivo: R-B ~140 sul pulsante
    "Attacco!" sia nel primario che nel Villaggio Costruttori).
    """
    if not _home_pixel_says_home():
        return False
    time.sleep(0.4)
    return _home_pixel_says_home()


# Cambio villaggio (v3.6): Clash of Clans resta sull'ultimo villaggio
# visitato tra un avvio e l'altro (primario o Villaggio Costruttori) - se
# l'utente (o una sessione precedente del bot del Villaggio Costruttori) ha
# lasciato aperto il villaggio sbagliato, questo bot partirebbe alla cieca
# usando le proprie coordinate sullo schermo sbagliato. Calibrato dal vivo
# il 2026-07-30 con screenshot reali (non a occhio):
# - Dal Villaggio Costruttori la barca di ritorno è semi-coperta dalla barra
#   risorse in alto a destra nella vista di default: un tap diretto lì apre
#   per sbaglio il tooltip "Max: N" della barra elisir (stesso comportamento
#   di ELIXIR_BAR_POINT) invece di toccare la barca. Serve prima un pan
#   della camera per portarla in una zona libera, poi toccarla lì.
#
# v3.8 (2026-08-04): stesso problema scoperto anche nella direzione
# opposta. BOAT_TO_BUILDER_POINT era tarato come "badge fisso sull'acqua,
# tap diretto" - ma un nuovo badge dell'evento stagionale ("Scheda degli
# incarichi", icona con countdown "27g 12h", non presente al momento della
# calibrazione originale) si è aggiunto sopra quel punto esatto della UI,
# intercettando il tap prima che arrivasse alla barca sottostante:
# switch_to_village("costruttore") falliva sempre (2 tentativi, "Cambio
# fallito"), verificato dal vivo. Fix: stesso schema pan+tap già usato per
# il tragitto di ritorno. Nuove coordinate confermate dal vivo.
BOAT_TO_BUILDER_PAN = ((1300, 700), (1650, 260))  # pan per rivelare la barca (villaggio primario)
BOAT_TO_BUILDER_POINT = (830, 390)                # barca per il Villaggio Costruttori, dopo il pan
BOAT_TO_PRIMARY_PAN = ((1400, 300), (700, 700))   # pan per rivelare la barca di ritorno
BOAT_TO_PRIMARY_POINT = (1670, 730)               # barca di ritorno, dopo il pan (ricalibrato 2026-08-04:
                                                   # 1598,580 non cadeva più sulla barca dopo il pan - la
                                                   # base/scenario del Villaggio Costruttori è cambiato dal
                                                   # 2026-07-30, non un badge stavolta ma la barca stessa
                                                   # ferma in un punto diverso dopo lo stesso pan)

# Distingue i due villaggi guardando il colore medio di una striscia in
# alto, fuori da qualsiasi edificio/HUD: verde (erba, canale G nettamente
# sopra il canale B) nel villaggio primario, blu/teal (roccia notturna,
# B sopra G) nel Villaggio Costruttori. Calibrato su screenshot reali di
# entrambi (G-B ~ +70 primario, ~ -13 costruttore su questa striscia).
VILLAGE_CHECK_REGION = {"left": 600, "top": 0, "width": 700, "height": 15}
VILLAGE_CHECK_GB_THRESHOLD = 20

# v3.14 (2026-08-10): stesso fix del bot del Villaggio Costruttori (v0.21),
# applicato qui per prevenzione anche se non e' questo lo script che ha
# fallito dal vivo oggi - la barca e' lo stesso tipo di oggetto fragile a
# coordinate fisse (vedi commento sopra su BOAT_TO_BUILDER_PAN/POINT). Prima
# del tap puntuale, cerca la barca via template matching in una finestra
# centrata sul punto calibrato: se la trova (anche spostata), tappa la
# posizione trovata; se non la trova, ricade sul vecchio tap puntuale
# esatto (nessuna regressione). Non ancora osservato dal vivo un fallimento
# reale di QUESTA funzione da correggere - miglioramento preventivo, non
# una riproduzione del bug di oggi (quello era in bot_costruttori.py).
BOAT_MATCH_SCALES = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15)
BOAT_MATCH_MIN_CONFIDENCE = 0.55
BOAT_MATCH_SEARCH_MARGIN = 160
BOAT_TO_BUILDER_REF_FILE = "boat_to_builder_ref.png"
BOAT_TO_PRIMARY_REF_FILE = "boat_to_primary_ref.png"
_boat_to_builder_ref = cv2.imread(BOAT_TO_BUILDER_REF_FILE)
_boat_to_primary_ref = cv2.imread(BOAT_TO_PRIMARY_REF_FILE)


def _find_boat(frame, template, around_point, margin=BOAT_MATCH_SEARCH_MARGIN):
    """Cerca `template` dentro una finestra centrata su `around_point` (+/-
    margin), provando le scale in BOAT_MATCH_SCALES per tollerare un po' di
    variazione di zoom. Ritorna il centro assoluto del miglior match se
    sopra BOAT_MATCH_MIN_CONFIDENCE, altrimenti None (il chiamante ricade
    sul tap puntuale calibrato)."""
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


def detect_village_type(frame=None):
    """Ritorna 'primario' o 'costruttore' guardando lo schermo attuale.
    Presuppone di essere già su una schermata home (villaggio primario o
    Villaggio Costruttori) - il risultato non ha senso durante
    scouting/battaglia.
    """
    if frame is None:
        frame = adb_screenshot()
    l, t = VILLAGE_CHECK_REGION["left"], VILLAGE_CHECK_REGION["top"]
    w, h = VILLAGE_CHECK_REGION["width"], VILLAGE_CHECK_REGION["height"]
    crop = frame[t:t + h, l:l + w].astype(np.int32)
    b_mean = crop[:, :, 0].mean()
    g_mean = crop[:, :, 1].mean()
    return "primario" if (g_mean - b_mean) > VILLAGE_CHECK_GB_THRESHOLD else "costruttore"


def switch_to_village(target, max_attempts=2):
    """Se non siamo già sul villaggio `target` ('primario' o 'costruttore'),
    tocca la barca per passarci. Va chiamata solo quando is_home_screen() è
    già True - non gestisce stati intermedi (scouting/battaglia).
    """
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
            point, template = BOAT_TO_BUILDER_POINT, _boat_to_builder_ref
        else:
            adb_swipe(BOAT_TO_PRIMARY_PAN[0][0], BOAT_TO_PRIMARY_PAN[0][1],
                      BOAT_TO_PRIMARY_PAN[1][0], BOAT_TO_PRIMARY_PAN[1][1])
            time.sleep(0.8)
            point, template = BOAT_TO_PRIMARY_POINT, _boat_to_primary_ref

        found = _find_boat(adb_screenshot(), template, point)
        if found is not None:
            print(f"[VILLAGGIO] Barca trovata via template match a {found} (punto calibrato: {point}).")
            adb_tap(*found)
        else:
            adb_tap(*point)
        time.sleep(4.0)

    # v3.9: il controllo veniva fatto solo PRIMA di ogni tap, mai dopo
    # l'ultimo - scoperto dal vivo il 2026-08-04: il cambio a volte riesce
    # solo al secondo tentativo (es. il primo tap arriva mentre la barca
    # non ha ancora finito un'animazione), ma la funzione tornava comunque
    # False perché il ciclo finiva subito dopo l'azione, senza ricontrollare.
    if detect_village_type() == target:
        print(f"[VILLAGGIO] Ora siamo su '{target}'.")
        return True

    print(f"[VILLAGGIO] Cambio fallito dopo {max_attempts} tentativi, siamo ancora su '{detect_village_type()}'.")
    return False


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

    # Trovato dal vivo: Tesseract a volte "duplica" una cifra che non esiste
    # davvero nell'immagine (es. legge 6400500 dove lo schermo mostra
    # 640500), facendo scattare attacchi su basi in realta' sotto soglia.
    # Un primo tentativo di validazione contava le macchie bianche in TUTTA
    # l'immagine e le confrontava col numero di cifre lette: durante lo
    # scouting pero' il testo del bottino e' sovrapposto al rendering 3D dal
    # vivo del villaggio nemico (non un pannello UI solido), che spesso crea
    # macchie bianche di dimensioni paragonabili alle cifre ma estranee al
    # numero, facendo scartare quasi ogni lettura valida. Ora si valida ogni
    # cifra singolarmente: si controlla che dentro il riquadro che Tesseract
    # stesso assegna a quella cifra ci sia davvero inchiostro. Il rumore di
    # sfondo fuori da quei riquadri non influisce piu' sul risultato.
    boxes_raw = pytesseract.image_to_boxes(mask, config=ocr_config)
    h, w = mask.shape
    digits = ""
    for line in boxes_raw.strip().splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        left, bottom, right, top = (int(p) for p in parts[1:5])
        y0, y1 = max(0, h - top), min(h, h - bottom)
        x0, x1 = max(0, left), min(w, right)
        roi = mask[y0:y1, x0:x1]
        ink_ratio = (roi > 127).mean() if roi.size else 0.0
        if ink_ratio < 0.12:
            print(f"[OCR] Lettura scartata: cifra '{parts[0]}' con solo {ink_ratio:.0%} di inchiostro nel suo riquadro, probabile lettura fantasma ({debug_name}).")
            return None
        digits += parts[0]

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


def read_battle_damage():
    """Legge la percentuale di "Danno complessivo" mostrata durante la
    battaglia (basso a destra). Ritorna None se l'OCR non trova nulla
    (es. schermata cambiata, popup sopra, ecc.) - il chiamante deve
    gestire il caso in modo sicuro, non assumere che sia sempre leggibile.

    Non riusa `_ocr_region_to_int()` (quella e' per numeri con separatore
    delle migliaia, whitelist solo cifre): qui il testo e' "N%", e con
    whitelist solo-cifre Tesseract forza comunque il simbolo "%" a
    diventare la cifra piu' simile (visto dal vivo: "36%" letto come
    "365") invece di ignorarlo. Whitelist con "%" incluso + psm 7 (singola
    riga, l'unica modalita' testata che legge in modo affidabile sia "2%"
    che "36%" su questo font) risolve; il simbolo va poi scartato a mano.
    """
    frame = adb_screenshot()
    l, t = OCR_REGION_DAMAGE["left"], OCR_REGION_DAMAGE["top"]
    w, h = OCR_REGION_DAMAGE["width"], OCR_REGION_DAMAGE["height"]
    crop = frame[t:t + h, l:l + w]

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([180, 60, 255]))
    mask = cv2.resize(mask, None, fx=5.0, fy=5.0, interpolation=cv2.INTER_CUBIC)
    mask = cv2.copyMakeBorder(mask, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=0)
    cv2.imwrite("debug_damage.png", mask)

    ocr_config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789%"
    text = pytesseract.image_to_string(mask, config=ocr_config)
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


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


def read_storage_max(bar_point, debug_name, tooltip_region=None):
    """Legge la capacita' massima del deposito (oro, elisir o elisir nero)
    aprendo il tooltip che compare toccando la barra della risorsa in alto a
    destra (mostra "Max: N", "Produzione oraria: N", "In tesoreria: N"). Non
    e' un valore fisso nel codice perche' cambia ogni volta che si potenzia
    un deposito. Il tap sullo stesso punto e' un toggle: un secondo tap
    chiude di nuovo il tooltip, cosi' non si lascia in giro nulla di aperto.

    `tooltip_region` di default (oro/elisir, le due barre piu' in alto)
    e' STORAGE_MAX_TOOLTIP_REGION - la barra elisir nero (piu' in basso)
    apre il tooltip piu' in basso a sua volta, serve una regione diversa
    (DARK_ELIXIR_MAX_TOOLTIP_REGION, verificata dal vivo il 2026-08-10).
    """
    if tooltip_region is None:
        tooltip_region = STORAGE_MAX_TOOLTIP_REGION
    adb_tap(*bar_point)
    time.sleep(1.0)
    frame = adb_screenshot()
    l, t = tooltip_region["left"], tooltip_region["top"]
    w, h = tooltip_region["width"], tooltip_region["height"]
    crop = frame[t:t + h, l:l + w]
    text = pytesseract.image_to_string(crop, config="--psm 6")
    cv2.imwrite(f"debug_storage_max_{debug_name}.png", crop)
    adb_tap(*bar_point)
    time.sleep(0.8)

    # v3.14: bug reale trovato dal vivo sul tooltip dell'elisir nero - il
    # vecchio regex r"Max[^\d]*([\d.,\s]+)" si fermava a meta' numero
    # ("430" invece di "430000") perche' Tesseract a volte inserisce un
    # carattere estraneo tra i gruppi di cifre (osservato dal vivo: "Max:
    # ,430-000))|_" - il trattino non fa parte della classe di caratteri
    # tollerati dal vecchio regex, quindi il resto veniva scartato).
    # Probabile causa: la barra elisir nero ha il contatore gemme "1.560"
    # che si sovrappone visivamente al tooltip (non capita con oro/elisir,
    # tooltip in una zona piu' libera). Fix piu' robusto: invece di provare
    # a enumerare ogni possibile carattere estraneo, si prende l'intera riga
    # che contiene "Max" e si scartano TUTTI i caratteri non numerici da
    # quella riga sola - tollera qualunque simbolo estraneo Tesseract possa
    # inserire in mezzo, non solo quelli previsti in anticipo.
    max_line = next((line for line in text.splitlines() if "max" in line.lower()), None)
    if max_line is None:
        return None
    # v3.14 (raffinato dopo test dal vivo su Windows, non solo sul Mac -
    # Tesseract non da' lo stesso identico output su piattaforme diverse per
    # questo stesso identico screenshot): oltre al trattino in mezzo alle
    # cifre (visto dal Mac: "Max:,430-000))|_"), su Windows e' comparsa
    # anche una cifra estranea PRIMA di "Max" sulla stessa riga (es. "2
    # Max:,430-000) |" - probabile artefatto del bordo del tooltip letto
    # come una cifra). Prendere tutte le cifre della riga intera avrebbe
    # incluso anche quella, gonfiando il risultato (430000 -> 2430000).
    # Si prende invece solo la sottostringa DA "max" in poi sulla riga,
    # cosi' si tollera qualunque simbolo estraneo TRA le cifre (il trattino)
    # senza pero' raccogliere cifre estranee PRIMA della parola "Max".
    idx = max_line.lower().index("max")
    digits = re.sub(r"[^\d]", "", max_line[idx:])
    return int(digits) if digits else None


def storage_is_full(threshold=STORAGE_FULL_THRESHOLD):
    """True se ALMENO UNA tra oro ed elisir in casa e' oltre `threshold`
    della propria capacita' massima (letta dal vivo, vedi read_storage_max)
    E l'elisir nero in casa e' anche lui sopra la propria soglia
    (`home_low_dark_elixir`). Usato a fine sessione per decidere se
    continuare a farmare o fermarsi a investire nelle mura: invece di un
    numero fisso di attacchi, si continua finche' i depositi non sono
    davvero pieni (scelta esplicita dell'utente, per non sprecare bottino
    che andrebbe perso perche' il deposito e' gia' colmo).

    Basta UNA valuta piena tra oro/elisir (non serve che lo siano
    entrambe): se l'elisir e' gia' colmo ma l'oro no (es. la sessione sta
    dando priorita' all'oro perche' scarso), continuare ad attaccare
    sprecherebbe comunque tutto l'elisir guadagnato in ogni attacco. Meglio
    fermarsi subito e investire quello che c'e' nelle mura (try_wall_upgrade
    prova comunque entrambe le valute, vedi _run_wall_upgrade_round) -
    scoperto dal vivo il 2026-07-25: con la vecchia condizione "entrambe
    piene" l'elisir restava sprecato attacco dopo attacco in attesa che
    anche l'oro si riempisse.

    ECCEZIONE (v3.13, bug vero trovato dal vivo il 2026-08-09): se la
    valuta NON piena e' sotto STORAGE_LOW_RATIO (50%) della propria
    capacita' massima, NON ci si ferma anche se l'altra e' gia' piena.
    Scoperto dal vivo: elisir pieno ma oro a 7/22 milioni (32%,
    "praticamente vuoto" per l'utente) - il bot si fermava comunque, senza
    mai dare tempo all'oro di risalire. Stessa filosofia di protezione gia'
    esistente sotto per l'elisir nero, estesa qui a oro/elisir tra loro (con
    una soglia proporzionale alla capacita' vera, non un numero assoluto
    come home_low_dark_elixir - vedi commento su STORAGE_LOW_RATIO per
    perche' i campi home_low_gold/home_low_elixir gia' in config non erano
    adatti a questo scopo).

    L'elisir nero invece e' un AND, non un OR con gli altri due: bug reale
    trovato il 2026-08-02: l'utente aveva l'elisir nero vuoto ma il bot si
    fermava comunque non appena oro/elisir normale erano pieni, senza mai
    dargli la possibilita' di accumularne - perche' storage_is_full()
    ignorava del tutto l'elisir nero. Ora, se e' sotto soglia, i depositi
    non sono mai considerati "pieni" (si continua a farmare, fino al tetto
    di sicurezza sul numero di attacchi/durata sessione se il farming di
    elisir nero e' lento) indipendentemente da oro/elisir.

    v3.14: "sotto soglia" per l'elisir nero significa ora la stessa cosa che
    per oro/elisir - sotto STORAGE_FULL_THRESHOLD della vera capacita' letta
    dal tooltip (DARK_ELIXIR_BAR_POINT), non piu' un numero assoluto fisso
    (home_low_dark_elixir, rimasto in config solo per
    determine_priority_resource(), usato a inizio sessione con un significato
    diverso). Vedi il commento sulla costante per il bug reale che questo
    risolve.

    Se la lettura della capacita' massima di oro/elisir fallisce (OCR/tooltip
    inatteso), ritorna False per sicurezza: meglio affidarsi al tetto di
    sicurezza a numero fisso di attacchi che rischiare un ciclo che non si
    ferma mai.
    """
    home = read_home_resources()
    gold_max = read_storage_max(GOLD_BAR_POINT, "gold")
    elixir_max = read_storage_max(ELIXIR_BAR_POINT, "elixir")

    if not gold_max or not elixir_max:
        print("[STORAGE] Lettura capacita' massima non riuscita, mi affido al tetto di sicurezza sul numero di attacchi.")
        return False
    if home.get("gold") is None or home.get("elixir") is None:
        return False

    # Controllo di sanita': il massimo non puo' mai essere inferiore a
    # quanto c'e' gia' in casa. Tesseract a volte "perde" delle cifre su
    # numeri con separatori delle migliaia (visto dal vivo: "26 000 000"
    # letto come "26000") - se capita, la lettura e' inutilizzabile, meglio
    # scartarla che calcolare una percentuale assurda.
    if gold_max < home["gold"] or elixir_max < home["elixir"]:
        print(f"[STORAGE] Lettura capacita' inverosimile (oro max {gold_max}, elisir max {elixir_max} - inferiori a quanto gia' in casa), scarto e mi affido al tetto di sicurezza.")
        return False

    gold_ratio = home["gold"] / gold_max
    elixir_ratio = home["elixir"] / elixir_max
    print(f"[STORAGE] Oro {home['gold']}/{gold_max} ({gold_ratio:.0%}), Elisir {home['elixir']}/{elixir_max} ({elixir_ratio:.0%}).")
    gold_full = gold_ratio >= threshold
    elixir_full = elixir_ratio >= threshold
    if not (gold_full or elixir_full):
        return False

    # Bug vero trovato dal vivo il 2026-08-09: elisir (e elisir nero) pieni
    # ma oro a 7/22 milioni (32%, "praticamente vuoto" per l'utente) - il
    # bot si fermava comunque (bastava una valuta piena, vedi sopra) senza
    # mai dare tempo all'oro di risalire. Tentativo iniziale con
    # home_low_gold/home_low_elixir (gia' in config) scartato subito: quei
    # campi sono soglie assolute piccole (default 300.000) pensate per
    # determine_priority_resource() a inizio sessione su un account con
    # depositi ancora piccoli - su un deposito da 22 milioni 300.000 e'
    # comunque "quasi vuoto" nello stesso senso lamentato dall'utente, quindi
    # non avrebbero protetto questo caso reale. Serve invece una soglia
    # proporzionale alla capacita' vera del deposito (STORAGE_LOW_RATIO):
    # se la valuta NON piena e' sotto questa percentuale della propria
    # capacita' massima, vale la pena continuare a farmare anche se l'altra
    # e' gia' piena, invece di fermarsi e sprecare l'occasione.
    if gold_full and not elixir_full and elixir_ratio < STORAGE_LOW_RATIO:
        print(f"[STORAGE] Elisir ancora scarso ({elixir_ratio:.0%}), continuo a farmare anche se l'oro e' pieno.")
        return False
    if elixir_full and not gold_full and gold_ratio < STORAGE_LOW_RATIO:
        print(f"[STORAGE] Oro ancora scarso ({gold_ratio:.0%}), continuo a farmare anche se l'elisir e' pieno.")
        return False

    dark_elixir = home.get("dark_elixir")
    if dark_elixir is None:
        # Lettura fallita: stessa scelta di sicurezza usata sopra per
        # oro/elisir max quando la lettura non riesce - meglio continuare a
        # farmare un altro ciclo (affidandosi al tetto di sicurezza su
        # attacchi/durata sessione) che fermarsi per errore scambiando un
        # intoppo OCR transitorio per "elisir nero pieno". Scoperto dal vivo
        # il 2026-08-07: il vecchio default (True, "considera pieno") ha
        # fatto fermare il bot dopo 7 attacchi con l'elisir nero all'84.000
        # su 400.000 di soglia, solo perche' quella singola lettura era
        # fallita ("lettura fantasma").
        return False

    # v3.14: come oro/elisir, "pieno" ora significa sopra STORAGE_FULL_THRESHOLD
    # della vera capacita' letta dal tooltip - non piu' una soglia assoluta
    # fissa (vedi commento sulla costante DARK_ELIXIR_BAR_POINT per il bug
    # reale che questo risolve). Stessa scelta di sicurezza delle altre due
    # valute: se la lettura del massimo fallisce o risulta inverosimile
    # (minore di quanto gia' in casa - es. una lettura OCR "fantasma" con una
    # cifra di troppo), NON si considera pieno, si continua a farmare.
    dark_elixir_max = read_storage_max(DARK_ELIXIR_BAR_POINT, "dark_elixir", DARK_ELIXIR_MAX_TOOLTIP_REGION)
    if not dark_elixir_max:
        print("[STORAGE] Lettura capacita' massima elisir nero non riuscita, continuo a farmare anche se oro/elisir sono pieni.")
        return False
    if dark_elixir_max < dark_elixir:
        print(f"[STORAGE] Lettura capacita' elisir nero inverosimile (max {dark_elixir_max}, inferiore a quanto gia' in casa: {dark_elixir}), scarto e continuo a farmare.")
        return False

    dark_elixir_ratio = dark_elixir / dark_elixir_max
    print(f"[STORAGE] Elisir nero {dark_elixir}/{dark_elixir_max} ({dark_elixir_ratio:.0%}).")
    if dark_elixir_ratio < threshold:
        print("[STORAGE] Elisir nero ancora sotto soglia, continuo a farmare anche se oro/elisir sono pieni.")
        return False
    return True


def _find_text_center(frame, region, needle):
    """Cerca `needle` (case-insensitive, anche come sottostringa) nel testo
    OCR di una regione e ritorna il centro della prima occorrenza in
    coordinate assolute dello screenshot, oppure None se non trovato.
    Usato per il menu upgrade mura, dove il testo si trova su uno sfondo
    fotografico (il villaggio dietro il pannello semi-trasparente) invece
    che su un pannello UI solido: un threshold semplice sul bianco basta
    perche' qui, a differenza delle cifre del bottino, non serve la
    validazione per-carattere di _ocr_region_to_int (il rischio non e' una
    cifra fantasma ma solo non trovare la parola, gia' gestito ritornando
    None).
    """
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


# v3.14 (2026-08-10): causa vera trovata dal vivo del bug "Attacco! non
# sembra essersi aperto (popup imprevisto?)" segnalato dall'utente
# ("vedevo che stava attaccando ma diceva che non poteva attaccare perche'
# aveva una schermata davanti"). Lasciando il gioco inattivo per un po'
# (successo mentre indagavo su altro, dal vivo sullo stesso account) e'
# comparso il vero dialog nativo di Clash of Clans "C'e' nessuno? La
# connessione e' stata interrotta per inattivita'" con un pulsante
# "RICARICA GIOCO" - un dialog modale che assorbe il tap su ATTACK_BUTTON
# senza far succedere nulla, ma NON copre il pulsante "Attacco!" sottostante
# (resta visibile, ancora arancione), quindi is_home_screen() continua a
# leggere "siamo in home" anche con il dialog aperto sopra: il vecchio
# codice restava quindi bloccato a ritentare lo stesso tap alla cieca,
# fermandosi ogni ciclo successivo con lo stesso identico messaggio, finche'
# qualcuno non tocca manualmente RICARICA GIOCO - coerente con l'osservazione
# dell'utente (uno screenshot preso vicino nel tempo puo' mostrare un
# attacco in corso di UN ALTRO ciclo, mentre QUESTO ciclo resta bloccato dal
# dialog, dando l'impressione di una contraddizione).
#
# Rilevato via OCR (la parola "interrotta" nel corpo del messaggio, testo
# bianco che supera la soglia di _find_text_center - il testo teal di
# "RICARICA GIOCO" invece e' troppo scuro per quella soglia).
#
# ATTENZIONE - tap automatico su "RICARICA GIOCO" TENTATO e SCARTATO: testato
# dal vivo lo stesso giorno, ha chiuso l'intero processo HD-Player.exe
# (non solo il popup) invece di ricaricare la partita - BlueStacks e'
# rimasto giu' fino a un riavvio manuale completo (task Windows). Un
# emulatore che si chiude da solo durante una sessione automatica e senza
# supervisione e' un rischio peggiore del problema che si vuole risolvere
# (perde anche la calibrazione zoom camera, vedi dezoom_camera.ps1),
# quindi qui NON si tocca il dialog: si rileva, si manda una foto via
# Telegram (l'utente lo chiedeva a parte ogni volta, vedi il commento sopra)
# e si solleva un errore vero, cosi' main() ferma la sessione dopo pochi
# tentativi (MAX_CONSECUTIVE_ERRORS) invece di restare bloccato a ritentare
# alla cieca per tutta la sessione come oggi (8+ tentativi falliti di fila).
RECONNECT_DIALOG_REGION = {"left": 560, "top": 400, "width": 850, "height": 280}


def _check_reconnect_dialog():
    """True se il dialog nativo 'connessione interrotta per inattivita'' e'
    presente - manda anche una foto via Telegram per farlo vedere subito
    all'utente (nessun tap sul dialog, vedi commento sopra)."""
    frame = adb_screenshot()
    if _find_text_center(frame, RECONNECT_DIALOG_REGION, "interrotta") is None:
        return False
    debug_path = "debug_reconnect_dialog.png"
    cv2.imwrite(debug_path, frame)
    send_telegram_photo(
        debug_path,
        "🛑 Il gioco mostra 'Connessione interrotta per inattività' - non tocco da solo "
        "RICARICA GIOCO (rischia di chiudere l'emulatore, verificato dal vivo). "
        "Ricarica il gioco a mano, poi riavvia il bot.",
    )
    return True


def _find_action_bar_buttons(frame):
    """Trova i pulsanti (rettangoli bianchi arrotondati) nella barra azioni
    in basso dopo aver selezionato un muro, e li ritorna come lista di
    centri (x, y) ordinati da sinistra a destra.

    Molto piu' affidabile della ricerca testuale via OCR su questi
    pulsanti: le etichette ("Migliora ancora", "Aggiungi mura +1", ecc.)
    sono in caratteri piccoli e stilizzati che Tesseract legge male,
    scoperto dal vivo (risultati tipo "Migliona", "Mighona" invece di
    "Migliora", nessuna occorrenza pulita di "ancora" trovata affatto).
    I pulsanti stessi pero' sono rettangoli bianchi netti su sfondo vario,
    facili da individuare per contorno indipendentemente da cosa c'e'
    scritto sopra. L'ordine dei pulsanti e' sempre lo stesso per un dato
    stato del pannello (visto dal vivo: 5 pulsanti nella selezione singola
    da menu - Info, Migliora ancora, Migliora oro, Migliora elisir, N
    Migliora gemme - e 5 nella modalita' batch dopo "Migliora ancora" -
    Togli mura -1, Aggiungi +10, Aggiungi +1, Migliora oro, Migliora
    elisir), quindi chi chiama puo' indicizzare per posizione.
    """
    l, t, w, h = WALL_ACTION_BAR_REGION["left"], WALL_ACTION_BAR_REGION["top"], WALL_ACTION_BAR_REGION["width"], WALL_ACTION_BAR_REGION["height"]
    crop = frame[t:t + h, l:l + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw > 100 and bh > 100:  # scarta il rumore, tiene solo pulsanti veri
            boxes.append((l + x + bw // 2, t + y + bh // 2))
    boxes.sort(key=lambda p: p[0])
    return boxes


def _find_action_bar_buttons_retry(min_count, attempts=3, delay=0.8, debug_name=None):
    """Come _find_action_bar_buttons, ma ritenta prima di arrendersi.

    Scoperto dal vivo (segnalato dall'utente): a volte il bot trova il
    muro, lo seleziona, ma poi il flusso si interrompe senza fare
    l'upgrade - probabile causa, la singola pausa fissa dopo un tap non
    basta sempre perche' l'animazione (chiusura lista, apertura pannello)
    finisca, e il primo screenshot trova meno pulsanti del previsto anche
    se il pannello e' pronto un attimo dopo. Ritenta con un nuovo
    screenshot invece di rinunciare al primo tentativo.

    Se anche dopo tutti i tentativi il conteggio non torna, salva un
    debug_action_bar_<debug_name>.png (crop della barra pulsanti) - la
    prima volta che questo e' successo dal vivo (2026-07-26, "1 pulsante
    invece di 5") non c'era nessuna immagine per capire cosa fosse
    davvero a schermo in quel momento, solo il numero nel log.
    """
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


WALL_COST_LABEL_OFFSET = (0, -55)   # dal centro del pulsante "Migliora" al centro
                                     # dell'etichetta di costo sopra di esso
WALL_COST_LABEL_SIZE = (90, 15)     # meta' larghezza/altezza del ritaglio da leggere


def _wall_cost_is_red(frame, button_center):
    """True se il costo mostrato sopra il pulsante 'Migliora' (oro o
    elisir) e' colorato di rosso - il gioco lo fa quando quella valuta
    selezionata non basta a pagare le mura scelte.

    Scoperto dal vivo il 2026-07-27, in sostituzione della lettura OCR del
    costo (rimossa da _scroll_to_wall_entry): quella lettura si rompeva in
    modo sistematico su certe voci della lista mura. Il colore invece e'
    un segnale binario molto piu' robusto - non serve leggere la cifra,
    basta sapere se e' bianca (va bene) o rossa (non basta).

    Calibrato dal vivo su uno screenshot con lo stesso costo mostrato in
    entrambi i colori fianco a fianco (oro insufficiente/rosso, elisir
    sufficiente/bianco): il testo bianco ha R-G ~ 6-9, il rosso ~ 36 - la
    soglia di 20 sta comodamente a meta' tra i due, con ampio margine.
    """
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


BUILDER_BADGE_ZERO_REF_FILE = "builder_badge_zero_ref.png"
_builder_badge_zero_ref = cv2.imread(BUILDER_BADGE_ZERO_REF_FILE, cv2.IMREAD_GRAYSCALE)


def has_free_builder():
    """True se il badge costruttori in alto mostra un numero di 'liberi'
    diverso da zero. Non legge la cifra esatta (tentato con OCR, ma su un
    ritaglio cosi' stretto - una cifra sola piu' un pezzetto della "/"
    accanto - sia psm 13 che psm 7 si sono rivelati fragili dal vivo,
    a volte non leggendo nulla pur con una maschera pulita): invece
    confronta il ritaglio pixel-per-pixel con un riferimento dello "0"
    salvato in BUILDER_BADGE_ZERO_REF_FILE. Molto piu' affidabile perche'
    ci interessa solo "zero o non zero", non il valore esatto. Ritorna
    False anche se il riferimento di confronto non si carica: meglio
    saltare l'upgrade che rischiare una lettura sbagliata.
    """
    if _builder_badge_zero_ref is None:
        print("[MURA] Riferimento badge costruttori non trovato, salto per sicurezza.")
        return False

    frame = adb_screenshot()
    l = BUILDER_BADGE_REGION["left"]
    t = BUILDER_BADGE_REGION["top"]
    w = BUILDER_BADGE_REGION["width"]
    h = BUILDER_BADGE_REGION["height"]
    crop = frame[t:t + h, l:l + w]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([180, 60, 255]))
    cv2.imwrite("debug_builder_badge.png", mask)

    if mask.shape != _builder_badge_zero_ref.shape:
        return False
    match_ratio = (mask == _builder_badge_zero_ref).mean()
    is_zero = match_ratio > 0.95
    return not is_zero


def _scroll_to_wall_entry():
    """Scorre il menu upgrade finche' non trova la voce 'Muro x<N>', fino
    a un numero massimo di tentativi. Ritorna il centro della voce trovata,
    o None se non la trova.

    Non legge piu' il costo unitario da qui (rimosso il 2026-07-27): quella
    lettura OCR si rompeva in modo sistematico su certe voci della lista
    (una linea decorativa dell'interfaccia ai margini della zona di lettura
    veniva scambiata da Tesseract per una cifra fantasma, scartando
    l'intera lettura anche quando il numero vero era perfettamente
    leggibile). Il costo non serve piu': _run_wall_upgrade_round ora decide
    quante mura aggiungere osservando il COLORE del costo sul pulsante
    Migliora (il gioco lo mostra in rosso quando non basta la valuta
    selezionata) invece di calcolarlo da un numero letto via OCR.
    """
    for _ in range(WALL_MAX_SCROLL_ATTEMPTS):
        frame = adb_screenshot()
        center = _find_text_center(frame, WALL_DROPDOWN_REGION, "Muro")
        if center:
            return center
        (x1, y1), (x2, y2) = WALL_DROPDOWN_SCROLL
        adb_swipe(x1, y1, x2, y2, duration_ms=600)
        time.sleep(1.0)
    return None


def _run_wall_upgrade_round(force_currency=None):
    """Esegue un singolo giro di upgrade mura: apre il menu, trova la voce
    'Muro', seleziona quante piu' mura possibile con le risorse disponibili
    e conferma il pagamento. Un muro alla volta ("Aggiungi mura +1", mai
    "+10": le risorse disponibili non bastano quasi mai per batch cosi'
    grandi, scelta esplicita dell'utente - il gioco stesso puo' rifiutare il
    +10 con l'avviso "Rimangono da selezionare meno di 10 mura disponibili"
    se ne restano pochi di quel livello).

    `force_currency` ("oro"/"elisir"/None): se specificato paga sempre con
    quella valuta (usato per un secondo giro esplicito sull'altra valuta,
    vedi try_wall_upgrade); se None sceglie automaticamente quella piu'
    abbondante in casa (comportamento originale, primo giro).

    Ritorna una tupla (valuta_pagata, motivo_se_saltato): valuta_pagata e'
    "oro"/"elisir" se ha confermato un upgrade (motivo allora e' None);
    None se ha saltato, col motivo come stringa leggibile - usato da
    try_wall_upgrade per avvisare via Telegram invece di rinunciare in
    silenzio (scoperto dal vivo: dall'esterno un tentativo fallito qui e'
    indistinguibile da un crash, il bot si ferma comunque a fine sessione).
    """
    adb_tap(*BUILDER_BADGE_POINT)
    time.sleep(1.5)

    wall_center = _scroll_to_wall_entry()
    if not wall_center:
        # Riprova riaprendo il menu una volta prima di arrendersi: se il tap
        # sul badge non ha aperto il menu la prima volta (es. lag/animazione
        # in corso), scorrere un pannello chiuso non trova mai nulla.
        print("[MURA] Voce 'Muro' non trovata al primo giro, riprovo riaprendo il menu...")
        adb_tap(*BUILDER_BADGE_POINT)
        time.sleep(1.0)
        adb_tap(*BUILDER_BADGE_POINT)
        time.sleep(1.5)
        wall_center = _scroll_to_wall_entry()
    if not wall_center:
        print("[MURA] Non ho trovato la voce 'Muro' nel menu, salto.")
        deselect_all()
        return None, "voce 'Muro' non trovata nel menu"

    adb_tap(*wall_center)
    time.sleep(1.5)

    # Selezionare una voce dalla lista NON chiude la lista: resta aperta e
    # visibile in trasparenza dietro la barra pulsanti del muro selezionato
    # (verificato dal vivo, non e' un frame di transizione ma lo stato
    # stabile), confondendo il rilevamento dei pulsanti per contorno qui
    # sotto. Ritoccare il badge dei costruttori la chiude esplicitamente
    # (stesso "toggle" gia' usato per aprirla) senza deselezionare il muro.
    adb_tap(*BUILDER_BADGE_POINT)
    time.sleep(1.5)

    # Selezione singola da menu: pulsanti bianchi rilevati sono o 4 (Info |
    # Migliora ancora | Migliora oro | Migliora elisir) o 5 se compare anche
    # "Selez. Riga" (visto dal vivo che puo' comparire o no) - il pulsante
    # N Migliora a gemme e' colorato, non bianco, quindi non viene mai
    # incluso in questo conteggio. In entrambi i casi "Migliora ancora" e'
    # sempre il terzultimo (subito prima dei due Migliora oro/elisir).
    # Uso il retry: la lista messa qui sopra si chiude un attimo dopo il
    # nostro tap, il primo screenshot puo' arrivare prima che l'animazione
    # sia finita e trovare meno pulsanti del previsto.
    buttons = _find_action_bar_buttons_retry(4, debug_name="selezione")
    if len(buttons) < 4:
        print(f"[MURA] Barra pulsanti inattesa ({len(buttons)} pulsanti invece di 4-5), salto.")
        deselect_all()
        return None, f"barra pulsanti inattesa dopo la selezione ({len(buttons)} invece di 4-5)"

    ancora_center = buttons[-3]
    adb_tap(*ancora_center)
    time.sleep(1.2)

    home = read_home_resources()
    available_gold = home.get("gold") or 0
    available_elixir = home.get("elixir") or 0

    # Modalita' batch dopo "Migliora ancora": Togli mura -1 | Aggiungi +10 |
    # Aggiungi +1 | Migliora oro | Migliora elisir (stessa griglia a 5
    # posizioni, verificato dal vivo).
    buttons = _find_action_bar_buttons_retry(5, debug_name="batch")
    if len(buttons) < 5:
        # Scoperto dal vivo il 2026-07-26: capitato un caso con un solo
        # pulsante trovato anche dopo i retry (non solo un'animazione
        # lenta) - prima di arrendersi, riprovo il tap su "Migliora ancora"
        # una seconda volta, nel caso il primo non fosse arrivato a segno.
        print(f"[MURA] Barra pulsanti batch inattesa ({len(buttons)} invece di 5), ritento il tap su 'Migliora ancora'...")
        adb_tap(*ancora_center)
        time.sleep(1.5)
        buttons = _find_action_bar_buttons_retry(5, debug_name="batch")
    if len(buttons) < 5:
        print(f"[MURA] Barra pulsanti batch ancora inattesa ({len(buttons)} pulsanti invece di 5), salto.")
        deselect_all()
        return None, f"barra pulsanti batch inattesa ({len(buttons)} invece di 5)"

    add_one_point = buttons[2]
    remove_one_point = buttons[0]

    # Il costo e' lo stesso sia in oro che in elisir (verificato dal vivo:
    # entrambi i pulsanti "Migliora" mostrano lo stesso numero, che scala
    # allo stesso modo aggiungendo mura), quindi per scegliere la valuta
    # piu' abbondante basta confrontare le quantita' in casa - non serve
    # sapere il costo. Se non e' forzata una valuta specifica si sceglie
    # quella piu' abbondante (primo giro); altrimenti si usa quella
    # richiesta (secondo giro, per non sprecare l'altra se anche lei e'
    # quasi piena).
    if force_currency:
        pay_currency = force_currency
    else:
        pay_currency = "oro" if available_gold >= available_elixir else "elisir"
    pay_point = buttons[3] if pay_currency == "oro" else buttons[4]
    print(f"[MURA] Risorse in casa: {available_gold} oro, {available_elixir} elisir -> pago in {pay_currency}.")

    # Quante mura aggiungere: invece di calcolarlo da un costo unitario
    # letto via OCR (si rompeva in modo sistematico su certe voci della
    # lista - una linea decorativa dell'interfaccia catturata ai margini
    # della zona di lettura veniva scambiata per una cifra fantasma, vedi
    # storico in _scroll_to_wall_entry), si aggiunge un muro alla volta
    # controllando il COLORE del costo sul pulsante Migliora scelto: il
    # gioco lo mostra in rosso quando quella valuta non basta piu'. Si
    # parte gia' con 1 muro selezionato (default dopo "Migliora ancora").
    # Idea dell'utente, molto piu' robusta di leggere una cifra: un
    # segnale binario (rosso/non rosso) invece di dover riconoscere le
    # cifre esatte.
    frame = adb_screenshot()
    if _wall_cost_is_red(frame, pay_point):
        print(f"[MURA] Risorse insufficienti per anche solo il primo muro in {pay_currency}, non confermo nulla.")
        deselect_all()
        return None, "risorse insufficienti per almeno un muro"

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

    print(f"[MURA] Punto a {target_count} mura, pago in {pay_currency}.")

    buttons = _find_action_bar_buttons_retry(5, debug_name="dopo_aggiungi")
    if len(buttons) < 5:
        print("[MURA] Pulsanti spariti dopo gli 'Aggiungi mura', non confermo nulla per sicurezza.")
        deselect_all()
        return None, "pulsanti spariti dopo gli 'Aggiungi mura'"

    pay_point = buttons[3] if pay_currency == "oro" else buttons[4]
    adb_tap(*pay_point)
    time.sleep(1.5)

    # Scoperto dal vivo il 2026-07-25, mai visto prima in questo flusso:
    # il tap su "Migliora" NON spende subito le risorse, apre un secondo
    # dialog di conferma ("Migliora le mura" / "Vuoi davvero migliorare le
    # mura selezionate per <costo> Oro/Elisir?" con Annulla/OK). Senza
    # questo tap il flusso si blocca qui: nessuna spesa, muro mai messo in
    # coda. Il pulsante OK e' sempre allo stesso punto fisso dello schermo
    # (verificato identico anche sul dialog "Terminare battaglia?" di fine
    # attacco: e' un componente di dialog generico del gioco, non specifico
    # delle mura), quindi non serve rilevarlo dinamicamente.
    adb_tap(*GENERIC_DIALOG_OK_POINT)
    time.sleep(1.5)
    print(f"[MURA] Confermato upgrade di {target_count} mura, pagato in {pay_currency}.")
    send_telegram(f"🧱 Upgrade mura: messe in coda {target_count} mura (pagate in {pay_currency}).")

    # Dopo l'OK il dialog si chiude da solo, ma il muro resta selezionato
    # (pannello singolo con Info + Migliora, costo aggiornato al livello
    # successivo) - serve comunque un deselect esplicito.
    deselect_all()
    time.sleep(1.0)
    return pay_currency, None


def try_wall_upgrade():
    """A fine sessione (o all'avvio, se i depositi sono gia' pieni), se il
    flag 'auto_wall_upgrade' e' attivo: controlla se c'e' un costruttore
    libero e in caso positivo fa un giro di upgrade mura con la valuta piu'
    abbondante, poi - dato che oro ed elisir hanno lo stesso costo per muro
    e vogliamo svuotare entrambi i depositi quasi pieni invece di sprecare
    solo quello non speso nel primo giro - ne fa un secondo con l'altra
    valuta se e' rimasta abbastanza per almeno un altro muro. Ogni passaggio
    verifica lo stato reale dello schermo prima di proseguire, come
    run_attack(): se qualcosa non torna, si interrompe e torna a un punto
    neutro invece di rischiare tap alla cieca (vicino a questo menu, in
    alto a destra, c'e' anche il negozio con acquisti veri - scoperto dal
    vivo un tap impreciso che ci e' finito sopra).
    """
    if not _config.get("auto_wall_upgrade"):
        return

    global current_phase
    current_phase = "mura"
    write_status(running=True)
    print("\n[MURA] Controllo se posso mettere in coda un upgrade mura...")

    if not is_home_screen():
        print("[MURA] Non siamo nel villaggio, salto.")
        return

    if not has_free_builder():
        print("[MURA] Nessun costruttore libero, salto.")
        return
    print("[MURA] Almeno un costruttore libero.")

    first_currency, first_reason = _run_wall_upgrade_round()
    if not first_currency:
        # Nessun upgrade fatto nonostante un costruttore libero: dall'esterno
        # e' indistinguibile da un crash (il bot si ferma comunque a fine
        # sessione, senza aver speso nulla) - avviso subito invece di
        # lasciare che l'utente lo scopra solo guardando i depositi ancora
        # pieni (segnalato dal vivo, capitava senza nessuna notifica).
        print(f"[MURA] Nessun upgrade fatto ({first_reason}).")
        send_telegram(
            f"⚠️ Fase mura: nessun upgrade effettuato ({first_reason}). "
            f"Depositi probabilmente ancora pieni, il bot si e' fermato: serve un controllo manuale."
        )
        return

    # Secondo giro forzato sull'ALTRA valuta: oro ed elisir costano uguale
    # per muro, quindi se il primo giro ha speso la valuta piu' abbondante
    # l'altra potrebbe essere rimasta quasi piena e sprecata (richiesta
    # esplicita dell'utente: svuotare entrambi i depositi, non solo uno).
    # _run_wall_upgrade_round si ferma da sola senza confermare nulla se non
    # ne resta abbastanza nemmeno per un muro, quindi e' sicuro chiamarla
    # comunque invece di ricalcolare qui se vale la pena provarci.
    other_currency = "elisir" if first_currency == "oro" else "oro"
    print(f"[MURA] Provo un secondo giro pagando in {other_currency}, per non sprecare anche quella valuta...")
    second_currency, second_reason = _run_wall_upgrade_round(force_currency=other_currency)
    if not second_currency:
        # Stesso discorso del primo giro: senza questo avviso, un secondo
        # giro fallito (es. OCR del costo respinta come "lettura fantasma",
        # visto dal vivo il 2026-07-26) passava del tutto inosservato -
        # l'utente vedeva solo il messaggio di successo del primo giro e
        # scopriva la seconda valuta rimasta piena solo controllando a mano.
        print(f"[MURA] Secondo giro ({other_currency}) senza upgrade ({second_reason}).")
        send_telegram(
            f"⚠️ Fase mura: il giro in {other_currency} non ha fatto nessun upgrade ({second_reason}). "
            f"Quella valuta e' probabilmente rimasta piena."
        )


def determine_priority_resource():
    """Decide su quale risorsa concentrare la sessione: quella con il
    deficit maggiore rispetto alla propria soglia 'basso' (home_low_*). Se
    nessuna risorsa e' sotto soglia (o l'OCR fallisce su tutte), il
    default e' l'oro (non l'elisir): scelta esplicita dell'utente, visto
    che in pratica oro/elisir restano quasi sempre ben sopra soglia su un
    account sviluppato e la scelta di default capita spesso.
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
        return "gold", home
    return max(deficits, key=deficits.get), home


def scroll_down_by_drag():
    """Scroll verso il basso appena inizia la battaglia, per portare la
    vista nella posizione giusta prima di schierare le truppe.
    """
    print("[ACTION] Scroll verso il basso...")
    adb_swipe(DRAG_START[0], DRAG_START[1], DRAG_END[0], DRAG_END[1], int(DRAG_DURATION * 1000))
    time.sleep(0.7)


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
        time.sleep(random.uniform(0.08, 0.14))
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
        time.sleep(random.uniform(0.08, 0.14))
        # 2 tap su punti diversi invece di uno solo: se il primo non va a
        # segno (stesso problema visto con le truppe), il secondo copre.
        for _ in range(2):
            dx, dy = hero_points[point_idx % len(hero_points)]
            point_idx += 1
            adb_tap_jittered(dx, dy)
            time.sleep(random.uniform(*CLICK_INTERVAL_RANGE))

    time.sleep(random.uniform(0.9, 1.3))

    print("[DEPLOY] Attivo le abilità eroi...")
    for slot_x in HERO_SLOTS:
        adb_tap(slot_x, TROOP_BAR_Y)
        time.sleep(random.uniform(0.10, 0.16))


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
    global last_resources, current_phase, scout_progress
    threshold = _config[f"threshold_{priority_resource}"]
    current_phase = "scouting"
    start = time.time()
    any_read_succeeded = False
    for attempt in range(1, MAX_SKIP_ATTEMPTS + 1):
        time.sleep(0.5)

        if is_home_screen():
            print("[SCOUT] Siamo tornati al villaggio inaspettatamente, interrompo la ricerca.")
            scout_progress = None
            return False

        resources = read_available_resources()
        loot = resources.get(priority_resource)
        print(f"[SCOUT] Tentativo {attempt}/{MAX_SKIP_ATTEMPTS} - risorsa prioritaria ({priority_resource}): {loot} - tutte: {resources}")
        if any(v is not None for v in resources.values()):
            last_resources = resources
            any_read_succeeded = True

        scout_progress = {
            "attempt": attempt,
            "max_attempts": MAX_SKIP_ATTEMPTS,
            "resources": resources,
            "threshold": threshold,
        }
        write_status(running=True)

        if loot is not None and loot >= threshold:
            print(f"[SCOUT] {loot} >= {threshold} -> attacco questa base")
            return True

        if time.time() - start > SCOUT_TIME_BUDGET:
            if not any_read_succeeded:
                print("[SCOUT] Budget scaduto e NESSUNA lettura riuscita in tutto lo scouting - schermo probabilmente fuori calibrazione (es. zoom cambiato), non attacco alla cieca.")
                send_telegram("⚠️ Lo scouting non riesce a leggere nessuna risorsa da diversi tentativi (schermo probabilmente fuori calibrazione, es. zoom della camera cambiato). Salto questo ciclo invece di attaccare alla cieca - controlla lo schermo.")
                scout_progress = None
                return False
            print("[SCOUT] Budget di tempo scouting esaurito, attacco comunque l'ultima base trovata.")
            return True

        print("[SCOUT] Sotto soglia (o non letto) -> cerco un altro avversario")
        adb_tap(*SKIP_BUTTON)
        time.sleep(0.8)

    if not any_read_succeeded:
        print("[SCOUT] Limite tentativi raggiunto e NESSUNA lettura riuscita - schermo probabilmente fuori calibrazione (es. zoom cambiato), non attacco alla cieca.")
        send_telegram("⚠️ Lo scouting non riesce a leggere nessuna risorsa da diversi tentativi (schermo probabilmente fuori calibrazione, es. zoom della camera cambiato). Salto questo ciclo invece di attaccare alla cieca - controlla lo schermo.")
        scout_progress = None
        return False
    print("[SCOUT] Raggiunto il limite di tentativi, attacco comunque l'ultima base trovata.")
    return True


def wait_for_battle_start(countdown_started_at, fixed_wait=BATTLE_START_MAX_WAIT):
    """Aspetta che il countdown di matchmaking finisca e la battaglia
    inizi davvero.

    Il countdown decorre anche mentre si valutano/scartano gli avversari:
    non ricominciamo quindi da zero dopo aver scelto una base, ma aspettiamo
    solo i secondi che mancano. Provare a rilevare la transizione leggendo lo schermo (OCR sul
    bottino, colore di icone) si è rivelato inaffidabile nei test dal
    vivo: l'OCR a volte legge numeri residui/rumore invece di None, e le
    decorazioni della base (a tema, es. Pasqua/Natale) possono avere
    colori identici a quelli delle icone dell'interfaccia, generando falsi
    positivi/negativi. Molto più robusto aspettare semplicemente il tempo
    fisso del countdown di gioco (~28-30s) e poi verificare solo che non
    siamo tornati al villaggio (quell'unico controllo si è dimostrato
    affidabile).
    """
    elapsed = max(0.0, time.monotonic() - countdown_started_at)
    remaining = max(0.0, fixed_wait - elapsed)
    print(
        f"[WAIT] Countdown: trascorsi {elapsed:.1f}s, "
        f"aspetto ancora {remaining:.1f}s prima di schierare..."
    )
    time.sleep(remaining)

    if is_home_screen():
        print("[WAIT] Siamo al villaggio, la battaglia non è mai iniziata.")
        return False
    return True


def maybe_hesitate(chance=0.25, pause_range=(2.0, 6.0)):
    """Pausa di 'esitazione' casuale: non capita ad ogni attacco (solo
    con probabilita' `chance`), per non introdurre comunque un ritardo
    fisso e prevedibile ad ogni ciclo. Randomizzazione piu' spinta della
    v1.8, oltre a quella "leggera" sui tap gia' presente dalla v1.7."""
    if random.random() < chance:
        pause = random.uniform(*pause_range)
        print(f"[WAIT] Pausa di esitazione ({pause:.1f}s)...")
        time.sleep(pause)


def wait_for_battle_end():
    """Aspetta che la battaglia finisca leggendo periodicamente il "Danno
    complessivo": se non sale per DAMAGE_STALL_SECONDS le truppe sono
    verosimilmente morte/ferme e si termina subito, invece di aspettare
    sempre il tetto massimo fisso (comportamento fino alla v3.0). Il tetto
    massimo (BATTLE_DURATION_WAIT[1]) resta come rete di sicurezza se
    l'OCR smette di leggere il danno per qualche motivo.
    """
    _, max_wait = BATTLE_DURATION_WAIT
    started_at = time.monotonic()
    last_value = None
    last_change_at = started_at

    time.sleep(DAMAGE_GRACE_PERIOD)

    while time.monotonic() - started_at < max_wait:
        value = read_battle_damage()
        now = time.monotonic()

        if value is not None:
            if last_value is None or value > last_value:
                last_value = value
                last_change_at = now
            if value >= 100:
                print("[WAIT] Danno al 100%, termino subito.")
                return
        # Una lettura fallita (value is None - es. l'effetto grafico del
        # fulmine dei draghi elettrici copre il numero per un paio di
        # secondi, o un frame sfortunato) NON aggiorna last_change_at: conta
        # come "nessun nuovo danno visto in questo istante", non come prova
        # che la battaglia sia gia' finita. Bug trovato dal vivo il
        # 2026-07-29: la versione precedente terminava subito dopo due
        # letture fallite di fila (~4s), scambiando un effetto grafico
        # temporaneo per fine battaglia con truppe ancora vive e attive.

        stalled_for = now - last_change_at
        if stalled_for >= DAMAGE_STALL_SECONDS:
            print(f"[WAIT] Danno fermo (ultimo letto: {last_value}) da {stalled_for:.0f}s, termino.")
            return

        time.sleep(DAMAGE_POLL_INTERVAL)

    print(f"[WAIT] Tetto massimo di {max_wait:.0f}s raggiunto, termino comunque.")


def run_attack():
    """Un ciclo completo: cerca avversario, valuta, attacca, aspetta la
    fine della battaglia, torna al villaggio. Ogni fase verifica lo stato
    reale dello schermo prima di procedere: se qualcosa va storto (es. si
    torna al villaggio prima del previsto) il ciclo si interrompe subito
    invece di continuare a schierare truppe alla cieca.
    """
    maybe_hesitate()
    # A volte un popup imprevisto sopra al villaggio (es. "Miglioramento
    # completato!", offerte, eventi) assorbe il tap su "Attacco!": la
    # sequenza di tap successivi (pensati per le schermate seguenti) allora
    # cade ancora sul villaggio, rischiando di premere pulsanti sbagliati
    # (es. il Negozio, se la sua posizione coincide con una di quelle
    # coordinate). Per questo verifichiamo che il tap abbia funzionato
    # davvero (siamo usciti dal villaggio) prima di proseguire, invece di
    # fidarci ciecamente del solo tempo di attesa.
    adb_tap(*ATTACK_BUTTON)
    time.sleep(1.2)

    if is_home_screen():
        # v3.14: prima di ritentare alla cieca, controlla se il vero motivo
        # e' il dialog nativo "connessione interrotta per inattivita'" (vedi
        # _check_reconnect_dialog) - se e' quello, ritentare non serve a
        # nulla (il dialog non si chiude da solo): meglio fermare subito la
        # sessione con un errore vero (raise, contato da main() nel tetto
        # MAX_CONSECUTIVE_ERRORS) che ripetere lo stesso tap alla cieca per
        # il resto della sessione come successo dal vivo oggi (8+ cicli
        # falliti di fila con lo stesso identico messaggio).
        if _check_reconnect_dialog():
            raise RuntimeError("Dialog 'connessione interrotta per inattività' rilevato: serve intervento manuale, non riprovo alla cieca.")

        print("[ATTACK] 'Attacco!' non sembra essersi aperto (popup imprevisto?), riprovo...")
        adb_tap(*ATTACK_BUTTON)
        time.sleep(1.5)

        if is_home_screen():
            if _check_reconnect_dialog():
                raise RuntimeError("Dialog 'connessione interrotta per inattività' rilevato: serve intervento manuale, non riprovo alla cieca.")
            print("[ATTACK] Ancora al villaggio dopo il secondo tentativo, salto questo ciclo.")
            debug_path = "debug_attack_stuck.png"
            cv2.imwrite(debug_path, adb_screenshot())
            send_telegram_photo(debug_path, "⚠️ Non riesco ad aprire la schermata di attacco (forse un popup blocca il villaggio). Salto un ciclo - ecco cosa vedo io in questo momento.")
            return

    adb_tap(*FIND_MATCH_BUTTON)
    time.sleep(1.6)
    adb_tap(*CONFIRM_ATTACK_BUTTON)
    countdown_started_at = time.monotonic()
    time.sleep(2.5)

    if not find_and_evaluate_opponent():
        print("[ATTACK] Scouting interrotto, salto questo ciclo.")
        return

    for resource, amount in last_resources.items():
        if amount is not None:
            session_totals[resource] += amount

    if not wait_for_battle_start(countdown_started_at):
        print("[ATTACK] La battaglia non è iniziata come previsto, salto lo schieramento.")
        return

    if is_home_screen():
        print("[ATTACK] Siamo al villaggio invece che in battaglia: non schiero nulla.")
        return

    global current_phase, scout_progress
    current_phase = "battaglia"
    scout_progress = None
    write_status(running=True)

    maybe_hesitate(chance=0.2, pause_range=(1.5, 4.0))
    deploy_army()

    wait_for_battle_end()

    print("[ACTION] Termino la battaglia...")
    adb_tap(*END_BATTLE_BUTTON)
    time.sleep(1.2)
    # Se abbiamo schierato truppe, compare il popup di conferma "Arrendersi?":
    # questo tap non fa nulla se il popup non c'è (tocca lo sfondo del risultato).
    adb_tap(*CONFIRM_END_BATTLE_BUTTON)
    time.sleep(1.6)

    print("[ACTION] Torno al villaggio...")
    adb_tap(*RETURN_HOME_BUTTON)
    time.sleep(1.6)
    adb_tap(*RETURN_HOME_BUTTON)  # nel caso serva un secondo tap (es. schermata forziere)
    time.sleep(1.6)


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
    home_ready = False
    for _ in range(15):
        if is_home_screen():
            home_ready = True
            break
        time.sleep(1.0)

    # Clash of Clans resta sull'ultimo villaggio visitato: se una sessione
    # precedente del bot del Villaggio Costruttori ha lasciato il gioco
    # aperto lì, questo bot (villaggio primario) partirebbe alla cieca
    # sullo schermo sbagliato. Vedi switch_to_village().
    if home_ready:
        print("[VILLAGGIO] Controllo di essere sul villaggio primario...")
        switch_to_village("primario")
    else:
        print("[VILLAGGIO] Non risultiamo su una schermata home dopo l'attesa, salto il controllo villaggio.")

    if _config["priority_mode"] in ("gold", "elixir", "dark_elixir"):
        # Priorita' forzata dalla dashboard: salta il rilevamento
        # automatico (e la lettura OCR delle risorse in casa, non serve).
        priority_resource = _config["priority_mode"]
        print(f"[HOME] Risorsa prioritaria forzata dalla dashboard: {priority_resource}")
    else:
        priority_resource, home = determine_priority_resource()
        print(f"[HOME] Risorse in casa: {home} -> risorsa prioritaria della sessione: {priority_resource}")

    # Se i depositi sono gia' quasi pieni all'avvio (es. bot fermo per un
    # po' mentre oro/elisir si riempivano da soli), l'upgrade mura va fatto
    # SUBITO, prima del primo attacco - altrimenti quell'attacco farma
    # bottino che va sprecato perche' il deposito e' gia' colmo. Il
    # controllo dopo ogni attacco (piu' sotto) da solo non basta: coprirebbe
    # solo il caso "si sono riempiti durante la sessione", non "erano gia'
    # pieni all'avvio".
    try:
        if storage_is_full():
            print("[STORAGE] Depositi gia' quasi pieni all'avvio, provo l'upgrade mura prima di attaccare.")
            try_wall_upgrade()
    except Exception as e:
        print(f"[STORAGE] Errore nel controllo iniziale dei depositi, proseguo con gli attacchi: {e}")
        send_telegram(f"⚠️ Errore nel controllo mura iniziale ({e}), proseguo comunque con gli attacchi.")

    start_time = time.time()
    session_start_time = start_time

    # v2.0: la sessione non si ferma piu' a un numero fisso di attacchi, ma
    # continua finche' i depositi di oro/elisir non sono quasi pieni (vedi
    # storage_is_full), per non farmare inutilmente ne' sprecare bottino
    # perso perche' il deposito e' gia' colmo - scelta esplicita dell'utente.
    # session_max_triggers resta come tetto di sicurezza (se la lettura
    # della capacita' dei depositi fallisce sistematicamente, es. per un
    # cambio di UI del gioco, la sessione si ferma comunque invece di
    # continuare all'infinito). Sessioni un po' irregolari (v1.8) anche qui,
    # cosi' non c'e' un pattern fisso riconoscibile da fuori.
    session_max_triggers = max(1, MAX_TRIGGERS - random.randint(0, 2))
    session_duration = max(300.0, SESSION_DURATION - random.uniform(0, 300))

    write_status(running=True)
    send_telegram(
        f"▶️ Bot avviato (v{VERSION}). Risorsa prioritaria: {priority_resource}. "
        f"Continua finche' i depositi non sono quasi pieni (tetto di sicurezza: "
        f"{session_max_triggers} attacchi o {int(session_duration/60)} minuti)."
    )

    # Se ADB/BlueStacks va giu' a meta' sessione (es. crash dell'emulatore),
    # ogni attacco fallisce subito con un'eccezione: senza un limite, il
    # ciclo riprovava ogni 5s fino a SESSION_DURATION, mandando un messaggio
    # Telegram di errore ad ogni tentativo (decine in pochi minuti). Scoperto
    # dal vivo durante un test. Dopo N errori di fila ci si ferma con un
    # solo avviso, invece di continuare a martellare alla cieca.
    MAX_CONSECUTIVE_ERRORS = 3
    consecutive_errors = 0
    session_ended_cleanly = True

    while True:
        now = time.time()

        if now - start_time > session_duration:
            msg = f"Sono passati {int(session_duration/60)} minuti, fermo il bot per timeout."
            print(f"\n[STOP] {msg}")
            send_telegram(f"⏱ {msg} Attacchi totali: {trigger_count}\n{format_totals_summary()}")
            write_status(running=False)
            append_history_entry(end_reason="timeout")
            break

        trigger_count += 1
        print(f"\n[ATTACCO {trigger_count}/{session_max_triggers}]")

        try:
            run_attack()
        except Exception as e:
            consecutive_errors += 1
            # str(e) su un CalledProcessError non include lo stderr del
            # comando (solo "returned non-zero exit status N") - senza
            # questo il log non dice MAI perche' un comando adb sia
            # fallito, solo che e' fallito (scoperto dal vivo il
            # 2026-08-12 mentre si diagnosticava un blocco del bridge adb).
            stderr_detail = getattr(e, "stderr", None)
            if stderr_detail:
                stderr_detail = stderr_detail.decode(errors="ignore").strip()
            print(f"[ERRORE] {e}" + (f" | stderr: {stderr_detail}" if stderr_detail else ""))
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                msg = f"Troppi errori di fila ({consecutive_errors}), mi fermo invece di continuare a riprovare alla cieca."
                print(f"[STOP] {msg}")
                send_telegram(f"🛑 {msg} Ultimo errore: {e}\nControlla che BlueStacks/ADB siano ok.")
                write_status(running=False)
                append_history_entry(end_reason="errori")
                session_ended_cleanly = False
                break
            send_telegram(f"⚠️ Errore durante l'attacco {trigger_count}: {e}")
            write_status(running=True)
            time.sleep(5.0)
            continue

        consecutive_errors = 0
        write_status(running=True)

        deposits_full = False
        try:
            deposits_full = storage_is_full()
        except Exception as e:
            print(f"[STORAGE] Errore durante il controllo depositi, ignoro e proseguo: {e}")

        if deposits_full:
            msg = f"✅ Depositi quasi pieni, mi fermo per investire nelle mura. Attacchi fatti: {trigger_count}."
            print(f"[STOP] {msg}")
            send_telegram(f"{msg}\n{format_totals_summary()}")
            write_status(running=False)
            append_history_entry()
            break

        if trigger_count >= session_max_triggers:
            msg = f"✅ Bot ha finito di farmare (tetto di sicurezza sul numero di attacchi, i depositi non risultavano ancora pieni). Raggiunti {trigger_count} attacchi."
            print(f"[STOP] {msg}")
            send_telegram(f"{msg}\n{format_totals_summary()}")
            write_status(running=False)
            append_history_entry()
            break

    # Upgrade mura (se richiesto dalle impostazioni) solo a fine sessione
    # "pulita": se ci siamo fermati per troppi errori di fila, ADB/BlueStacks
    # sono probabilmente in uno stato inaffidabile e tentare altri tap alla
    # cieca rischierebbe solo di peggiorare le cose invece di aiutare.
    if session_ended_cleanly:
        try:
            try_wall_upgrade()
        except Exception as e:
            print(f"[MURA] Errore durante l'upgrade mura: {e}")
            send_telegram(f"🛑 Errore durante l'upgrade mura, il bot si e' fermato: {e}")
        write_status(running=False)


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
