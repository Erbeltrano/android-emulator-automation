#!/usr/bin/env python3
"""Logica condivisa per pilotare il PC Windows (Wake-on-LAN + SSH + stato):
usata sia dal relay Telegram (telegram_relay.py) che dalla dashboard web
(dashboard.py), per non duplicare la stessa logica in due posti.

Solo libreria standard: nessuna dipendenza da installare.
"""
import base64
import json
import os
import socket
import subprocess
import time

WINDOWS_MAC = "A8:5E:45:B5:BF:F5"
WINDOWS_IP = "WINDOWS_PC_IP"  # riservato via app Fastweb il 2026-07-19 (era .89)
WINDOWS_BROADCAST = "LAN_BROADCAST_IP"
SSH_USER = "simon"
SSH_KEY = os.path.expanduser("~/.ssh/coc_bot_win")
# ControlMaster/ControlPersist: la prima chiamata apre una connessione SSH
# e la tiene aperta, le successive la riusano invece di rifare da zero
# l'handshake TCP+SSH+autenticazione. Scoperto dal vivo che senza riuso ogni
# singola chiamata (get_bot_status() ne fa fino a 3 di seguito) rischiava di
# incappare in un intoppo quando il PC Windows era sotto carico per via di
# BlueStacks/ADB, causando falsi negativi (es. il watchdog convinto che il
# PC fosse sparito dalla rete mentre una sessione era regolarmente in corso).
SSH_CONTROL_PATH = os.path.expanduser("~/.ssh/coc_bot_control-%r@%h:%p")
SSH_OPTS = [
    "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=6",
    "-o", "BatchMode=yes",
    "-o", "ControlMaster=auto",
    "-o", "ControlPersist=60s",
    "-o", f"ControlPath={SSH_CONTROL_PATH}",
]

BOT_LOG_PATH = r"C:\Users\simon\bot_log.txt"
BOT_COSTRUTTORI_LOG_PATH = r"C:\Users\simon\bot_costruttori_log.txt"
STATUS_PATH = r"C:\Users\simon\status.json"
CONFIG_PATH = r"C:\Users\simon\config.json"
HISTORY_PATH = r"C:\Users\simon\history.json"
SCREEN_REMOTE_PATH = "C:/Users/simon/screen_relay.png"  # slash, non backslash: scp
                                                         # raddoppia i backslash nel
                                                         # path remoto (bug noto del
                                                         # client SFTP), il file poi
                                                         # non si trova piu'
ADB_PATH = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"  # stesso path usato da run_bot.bat

DEFAULT_SETTINGS = {
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

WAKE_INITIAL_WAIT = 12   # cuscinetto minimo dopo il magic packet prima del primo controllo SSH
WAKE_SSH_RETRIES = 14
WAKE_SSH_RETRY_DELAY = 5


def send_magic_packet(mac=WINDOWS_MAC, repeats=5):
    """Manda il pacchetto Wake-on-LAN piu' volte: un singolo invio UDP
    non e' garantito e in pratica capita che si perda.

    Manda sia al broadcast di sottorete (LAN_BROADCAST_IP) che a quello
    globale (255.255.255.255): su alcune reti/interfacce il secondo da'
    OSError "No route to host" (visto dal vivo su questo Mac). Ogni invio
    e' avvolto nel proprio try/except cosi' un target che fallisce non
    interrompe ne' l'altro target ne' i tentativi successivi del ciclo.
    """
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for _ in range(repeats):
        for target in (WINDOWS_BROADCAST, "255.255.255.255"):
            try:
                sock.sendto(packet, (target, 9))
            except OSError:
                pass
        time.sleep(1)
    sock.close()


def ssh_run(command, timeout=15, retries=1):
    """Esegue un comando sul PC Windows via SSH. Ritorna (ok, stdout+stderr).

    Non usa text=True: l'output di cmd.exe/PowerShell in italiano puo'
    arrivare in una code page diversa da UTF-8 (es. accenti), che altrimenti
    farebbe crashare la decodifica automatica di subprocess.

    Riprova `retries` volte (con una breve pausa) prima di arrendersi: la
    connessione persistente (vedi SSH_OPTS) rende un secondo tentativo quasi
    gratuito, e copre gli intoppi momentanei che capitavano anche con una
    connessione sana.
    """
    full_cmd = ["ssh"] + SSH_OPTS + [f"{SSH_USER}@{WINDOWS_IP}", command]
    last_output = ""
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(full_cmd, capture_output=True, timeout=timeout)
            output = (result.stdout or b"") + (result.stderr or b"")
            if result.returncode == 0:
                return True, output.decode("utf-8", errors="replace")
            last_output = output.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            last_output = "timeout"
        except Exception as e:
            last_output = str(e)
        if attempt < retries:
            time.sleep(1.5)
    return False, last_output


def windows_reachable():
    ok, _ = ssh_run("echo ok", timeout=6)
    return ok


def python_running():
    ok, out = ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Select Id"')
    return ok and "Id" in out


def get_bot_status():
    """Stato completo per la dashboard/relay: PC acceso?, bot vivo?, dati
    da status.json (contatore attacchi, ultima soglia elisir letta, ...).
    """
    if not windows_reachable():
        return {"windows_on": False, "running": False}

    running = python_running()

    status_data = {}
    ok, out = ssh_run(f"powershell -Command \"Get-Content '{STATUS_PATH}' -ErrorAction SilentlyContinue\"")
    if ok and out.strip():
        try:
            status_data = json.loads(out.strip())
        except ValueError:
            status_data = {}

    return {
        "windows_on": True,
        "running": running,
        "trigger_count": status_data.get("trigger_count", 0),
        "priority_resource": status_data.get("priority_resource"),
        "last_resources": status_data.get("last_resources"),
        "session_totals": status_data.get("session_totals"),
        "session_start_time": status_data.get("session_start_time"),
        "version": status_data.get("version"),
        "phase": status_data.get("phase"),
        "scout_progress": status_data.get("scout_progress"),
    }


_NOISY_PREFIXES = ("[TELEGRAM] Richiesta a:", "[TELEGRAM] Status:")


def get_log_tail(lines=30):
    """Ultime righe del log, filtrando il rumore delle risposte HTTP
    grezze di Telegram (JSON lunghissimo, poco leggibile in una UI).
    """
    ok, out = ssh_run(f"powershell -Command \"Get-Content '{BOT_LOG_PATH}' -Tail {lines * 3} -ErrorAction SilentlyContinue\"")
    if not ok:
        return []
    clean = [
        line for line in out.splitlines()
        if line.strip() and not line.startswith(_NOISY_PREFIXES)
    ]
    return clean[-lines:]


def _wake_and_wait_reachable(progress):
    """Manda il magic packet e aspetta che il PC risponda via SSH.

    Prima faceva un'attesa cieca fissa (`WAKE_WAIT_SECONDS`, 35s) prima del
    primissimo controllo, indipendentemente da quanto il PC fosse in realta'
    gia' raggiungibile - osservato dal vivo il 2026-08-12 (più wake-up
    consecutivi nella stessa sessione): il primo controllo *dopo* l'attesa
    riusciva sempre al primo colpo, segno che il PC era pronto ben prima dei
    35s pieni. Ora si aspetta solo un breve cuscinetto (`WAKE_INITIAL_WAIT`,
    12s - un boot Windows/POST non puo' comunque essere piu' rapido di
    cosi') poi si passa a interrogare, cogliendo il PC pronto appena lo e'
    invece di aspettare sempre il massimo. Il margine totale di pazienza
    (`WAKE_SSH_RETRIES` alzato da 10 a 14 per compensare) resta uguale o
    superiore a prima: un boot lento non viene abbandonato prima.
    """
    send_magic_packet()
    time.sleep(WAKE_INITIAL_WAIT)

    for _ in range(WAKE_SSH_RETRIES):
        if windows_reachable():
            return True
        time.sleep(WAKE_SSH_RETRY_DELAY)

    progress("❌ Il PC Windows non risponde via SSH dopo il Wake-on-LAN. Controlla che sia acceso.")
    return False


def start_bot(progress=lambda msg: None):
    """Sveglia il PC Windows e avvia il bot.

    `progress(msg)` viene chiamato ad ogni passo importante: il chiamante
    decide cosa farne (mandarlo su Telegram, appenderlo al log della
    dashboard, ecc). Ritorna True se il bot risulta avviato.
    """
    progress("📡 Sveglio il PC Windows (Wake-on-LAN)...")
    if not _wake_and_wait_reachable(progress):
        return False

    if python_running():
        progress("ℹ️ Il bot risulta già in esecuzione sul PC Windows.")
        return True

    ok, out = ssh_run('schtasks /run /tn "CoCBot"')
    if ok:
        progress("✅ PC Windows sveglio, bot avviato.")
        return True

    progress(f"⚠️ PC svegliato ma il lancio del task ha dato un problema:\n{out}")
    return False


def start_bot_costruttori(progress=lambda msg: None):
    """Sveglia il PC Windows e avvia il bot del Villaggio Costruttori
    (`secondo_villaggio/bot_costruttori.py`, prima versione v0.2, confermata
    dal vivo il 2026-07-30: 200% danno/3 stelle su un ciclo di test). Stesso
    schema di `start_bot()`, ma lancia il task `CoCBotCostruttori` (creato
    il 2026-07-30 - a differenza di quanto annotato in sessioni precedenti,
    creare NUOVI task pianificati funziona regolarmente da questa macchina,
    non serve riusare per forza `CoCBot`), che esegue
    `run_bot_costruttori.bat` invece di `run_bot.bat`: stessa sequenza di
    avvio BlueStacks/CoC, ma lancia `bot_costruttori.py --cycles 0` (loop
    continuo) al posto del bot del villaggio primario.

    Il cambio di villaggio (se il gioco è rimasto aperto su quello
    sbagliato) è gestito dallo script stesso all'avvio, non qui - vedi
    `switch_to_village()` in `bot_costruttori.py`.
    """
    progress("📡 Sveglio il PC Windows (Wake-on-LAN)...")
    if not _wake_and_wait_reachable(progress):
        return False

    if python_running():
        progress("ℹ️ Un bot risulta già in esecuzione sul PC Windows (primario o Villaggio Costruttori).")
        return True

    ok, out = ssh_run('schtasks /run /tn "CoCBotCostruttori"')
    if ok:
        progress("✅ PC Windows sveglio, bot del Villaggio Costruttori avviato.")
        return True

    progress(f"⚠️ PC svegliato ma il lancio del task ha dato un problema:\n{out}")
    return False


def get_costruttori_log_tail(lines=30):
    """Ultime righe del log del bot Villaggio Costruttori (nessun filtro
    di rumore Telegram: quel bot logga molto meno del bot principale)."""
    ok, out = ssh_run(f"powershell -Command \"Get-Content '{BOT_COSTRUTTORI_LOG_PATH}' -Tail {lines} -ErrorAction SilentlyContinue\"")
    if not ok:
        return []
    return [line for line in out.splitlines() if line.strip()]


def _record_manual_stop():
    """Aggiunge a history.json un riepilogo della sessione interrotta a
    mano, prima di uccidere il processo: altrimenti stop manuali (da
    dashboard o Telegram) sparivano dallo storico, che registrava solo le
    sessioni finite da sole (fine cicli/timeout/troppi errori).
    """
    status = get_bot_status()
    if not status.get("running"):
        return  # nessuna sessione attiva, niente da registrare

    entry = {
        "start": status.get("session_start_time"),
        "end": time.time(),
        "duration_minutes": (
            round((time.time() - status["session_start_time"]) / 60, 1)
            if status.get("session_start_time") else None
        ),
        "trigger_count": status.get("trigger_count", 0),
        "priority_resource": status.get("priority_resource"),
        "totals": status.get("session_totals") or {"gold": 0, "elixir": 0, "dark_elixir": 0},
        "version": status.get("version"),
        "end_reason": "manuale",
    }

    ok, out = ssh_run(f"powershell -Command \"Get-Content '{HISTORY_PATH}' -ErrorAction SilentlyContinue\"")
    history = []
    if ok and out.strip():
        try:
            history = json.loads(out.strip())
        except ValueError:
            history = []
    history.append(entry)
    history = history[-50:]

    payload = json.dumps(history)
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    cmd = (
        "powershell -Command \"[System.IO.File]::WriteAllText("
        f"'{HISTORY_PATH}', [System.Text.Encoding]::UTF8.GetString("
        f"[System.Convert]::FromBase64String('{b64}')))\""
    )
    ssh_run(cmd)


def stop_bot(progress=lambda msg: None):
    """Ferma il bot, chiude BlueStacks e spegne il PC Windows."""
    if not windows_reachable():
        progress("💤 PC Windows già spento o non raggiungibile, niente da fermare.")
        return False

    progress("⛔ Fermo il bot, chiudo BlueStacks e spengo il PC...")
    _record_manual_stop()
    ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force"')
    ssh_run('powershell -Command "Get-Process -Name HD-Player -ErrorAction SilentlyContinue | Stop-Process -Force"')
    ssh_run("shutdown /s /t 5 /f")
    progress("✅ Fatto: bot fermato, BlueStacks chiuso, PC in spegnimento.")
    return True


_BLUESTACKS_SERVICES_RUN_KEY_PATH = r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_BLUESTACKS_SERVICES_RUN_KEY_NAME = "electron.app.BlueStacks Services"
_BLUESTACKS_SERVICES_RUN_KEY_VALUE = (
    r'"C:\Users\simon\AppData\Local\Programs\bluestacks-services\BlueStacksServices.exe" --hidden'
)


def _ps_encoded_command(script):
    """Incapsula uno script PowerShell come -EncodedCommand (UTF-16LE +
    base64), come da gotcha gia' documentata (SSH da bash + pipe/quote
    annidate si mangiano a vicenda). Usato solo dove il comando ha
    virgolette annidate che il pattern `powershell -Command "..."` usato
    altrove in questo file non reggerebbe (es. il valore della chiave di
    registro qui sotto, che contiene già virgolette doppie sue)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell -EncodedCommand {encoded}"


def pause_for_exam(progress=lambda msg: None):
    """Ferma bot/BlueStacks e disabilita tutto cio' che potrebbe farli
    ripartire da soli, SENZA spegnere il PC (a differenza di stop_bot()) -
    per quando lo stesso PC Windows serve anche per altro (es. esami
    universitari con software di proctoring, richiesta esplicita
    dell'utente 2026-08-12) e deve restare acceso e usabile, ma senza
    nulla di questo progetto in esecuzione o riattivabile per sbaglio (un
    comando Telegram/dashboard arrivato per errore non deve poter far
    ripartire nulla finche' non si chiama resume_after_exam()).

    Oltre al bot e all'emulatore vero e proprio (HD-Player), ferma anche
    componenti BlueStacks che restano attivi in background pure ad
    emulatore chiuso - scoperto dal vivo il 2026-08-12 controllando cosa
    girava con HD-Player gia' chiuso: `BlueStacksServices.exe` (il
    launcher/hub, non l'emulatore) si riavvia da solo ad ogni login
    Windows tramite una voce nel registro (`HKCU...\\Run`), e `BstkSVC.exe`
    viene ririlanciato ogni ora dal task pianificato `BlueStacksHelper_nxt`
    creato da BlueStacks stesso. Tutti e due hanno "bluestacks" nel nome
    processo/percorso - un rischio concreto se un software di controllo
    esame scansiona i nomi dei processi in esecuzione. Disabilitare i task
    (`/disable`) invece di cancellarli e rimuovere solo temporaneamente la
    voce di registro (ripristinata da `resume_after_exam()`): tutto
    reversibile con un solo comando, non serve ricreare nulla a mano.
    """
    if not windows_reachable():
        progress("💤 PC Windows già spento, niente da mettere in pausa.")
        return False

    progress("⏸️ Fermo bot/BlueStacks (compresi i componenti in background) e disabilito l'avvio automatico...")
    ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force"')
    ssh_run('powershell -Command "Get-Process -Name HD-Player -ErrorAction SilentlyContinue | Stop-Process -Force"')
    ssh_run(
        'powershell -Command "Get-Process -Name HD-Adb,BstkSVC,BlueStacksServices,BlueStacksAppplayerWeb '
        '-ErrorAction SilentlyContinue | Stop-Process -Force"'
    )
    ssh_run('schtasks /change /tn "CoCBot" /disable')
    ssh_run('schtasks /change /tn "CoCBotCostruttori" /disable')
    ssh_run('schtasks /change /tn "BlueStacksHelper_nxt" /disable')
    ssh_run(_ps_encoded_command(
        f"Remove-ItemProperty -Path '{_BLUESTACKS_SERVICES_RUN_KEY_PATH}' "
        f"-Name '{_BLUESTACKS_SERVICES_RUN_KEY_NAME}' -ErrorAction SilentlyContinue"
    ))
    progress(
        "✅ Bot, emulatore e componenti BlueStacks in background fermi, avvio automatico disabilitato. "
        "Il PC resta acceso e usabile normalmente. Per riprendere: resume_after_exam()."
    )
    return True


def resume_after_exam(progress=lambda msg: None):
    """Riabilita tutto cio' che pause_for_exam() ha disattivato: i task
    pianificati e la voce di registro di BlueStacksServices."""
    if not windows_reachable():
        progress("💤 PC Windows spento: riabilito comunque i task, si attiveranno al prossimo avvio raggiungibile.")
    ssh_run('schtasks /change /tn "CoCBot" /enable')
    ssh_run('schtasks /change /tn "CoCBotCostruttori" /enable')
    ssh_run('schtasks /change /tn "BlueStacksHelper_nxt" /enable')
    ssh_run(_ps_encoded_command(
        f"Set-ItemProperty -Path '{_BLUESTACKS_SERVICES_RUN_KEY_PATH}' "
        f"-Name '{_BLUESTACKS_SERVICES_RUN_KEY_NAME}' -Value '{_BLUESTACKS_SERVICES_RUN_KEY_VALUE}'"
    ))
    progress("✅ Avvio automatico riabilitato. Il bot può ripartire normalmente da dashboard/Telegram.")
    return True


def get_settings():
    """Parametri di farming attuali (letti da config.json sul PC Windows,
    con i default se il file non c'e' ancora).
    """
    ok, out = ssh_run(f"powershell -Command \"Get-Content '{CONFIG_PATH}' -ErrorAction SilentlyContinue\"")
    settings = dict(DEFAULT_SETTINGS)
    if ok and out.strip():
        try:
            data = json.loads(out.strip())
            settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        except ValueError:
            pass
    return settings


def save_settings(new_settings):
    """Scrive config.json sul PC Windows: letto dal bot al prossimo avvio
    (non ha effetto su una sessione gia' in corso).
    """
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in new_settings.items() if k in DEFAULT_SETTINGS})

    payload = json.dumps(settings)
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    cmd = (
        "powershell -Command \"[System.IO.File]::WriteAllText("
        f"'{CONFIG_PATH}', [System.Text.Encoding]::UTF8.GetString("
        f"[System.Convert]::FromBase64String('{b64}')))\""
    )
    ok, out = ssh_run(cmd)
    return ok


def capture_screen(local_path):
    """Cattura uno screenshot dell'emulatore (via ADB, stesso comando usato
    dal bot) sul PC Windows e lo scarica in locale su `local_path`.

    Ritorna (True, None) se riuscito, (False, motivo) altrimenti. Funziona
    anche a bot fermo, purche' BlueStacks sia ancora aperto: usa ADB
    direttamente, non passa dal processo Python del bot.
    """
    if not windows_reachable():
        return False, "PC Windows spento o non raggiungibile."

    ok, out = ssh_run(
        f'"{ADB_PATH}" exec-out screencap -p > "{SCREEN_REMOTE_PATH}"',
        timeout=20,
    )
    if not ok:
        return False, f"Screenshot ADB fallito (BlueStacks aperto?): {out.strip()}"

    scp_cmd = [
        "scp", "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=6",
        f"{SSH_USER}@{WINDOWS_IP}:{SCREEN_REMOTE_PATH}",
        local_path,
    ]
    try:
        result = subprocess.run(scp_cmd, capture_output=True, timeout=20)
        if result.returncode != 0:
            return False, result.stderr.decode("utf-8", errors="replace").strip()
    except Exception as e:
        return False, str(e)

    return True, None


def get_history(limit=20):
    """Riepiloghi delle ultime sessioni (letti da history.json sul PC
    Windows, scritto dal bot a fine sessione), più recenti prima.
    """
    ok, out = ssh_run(f"powershell -Command \"Get-Content '{HISTORY_PATH}' -ErrorAction SilentlyContinue\"")
    if not ok or not out.strip():
        return []
    try:
        history = json.loads(out.strip())
    except ValueError:
        return []
    return list(reversed(history[-limit:]))
