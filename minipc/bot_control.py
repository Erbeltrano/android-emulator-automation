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
WINDOWS_IP = "WINDOWS_PC_IP_OLD"
WINDOWS_BROADCAST = "LAN_BROADCAST_IP"
SSH_USER = "simon"
SSH_KEY = os.path.expanduser("~/.ssh/coc_bot_win")
SSH_OPTS = [
    "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=6",
    "-o", "BatchMode=yes",
]

BOT_LOG_PATH = r"C:\Users\simon\bot_log.txt"
STATUS_PATH = r"C:\Users\simon\status.json"
CONFIG_PATH = r"C:\Users\simon\config.json"
HISTORY_PATH = r"C:\Users\simon\history.json"

DEFAULT_SETTINGS = {
    "threshold_gold": 800000,
    "threshold_elixir": 800000,
    "threshold_dark_elixir": 3000,
    "home_low_gold": 300000,
    "home_low_elixir": 300000,
    "home_low_dark_elixir": 1500,
    "max_triggers": 20,
    "session_duration_minutes": 50,
}

WAKE_WAIT_SECONDS = 35   # attesa dopo il magic packet prima di provare SSH
WAKE_SSH_RETRIES = 10
WAKE_SSH_RETRY_DELAY = 5


def send_magic_packet(mac=WINDOWS_MAC, repeats=5):
    """Manda il pacchetto Wake-on-LAN piu' volte: un singolo invio UDP
    non e' garantito e in pratica capita che si perda.
    """
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for _ in range(repeats):
        sock.sendto(packet, (WINDOWS_BROADCAST, 9))
        sock.sendto(packet, ("255.255.255.255", 9))
        time.sleep(1)
    sock.close()


def ssh_run(command, timeout=15):
    """Esegue un comando sul PC Windows via SSH. Ritorna (ok, stdout+stderr).

    Non usa text=True: l'output di cmd.exe/PowerShell in italiano puo'
    arrivare in una code page diversa da UTF-8 (es. accenti), che altrimenti
    farebbe crashare la decodifica automatica di subprocess.
    """
    full_cmd = ["ssh"] + SSH_OPTS + [f"{SSH_USER}@{WINDOWS_IP}", command]
    try:
        result = subprocess.run(full_cmd, capture_output=True, timeout=timeout)
        output = (result.stdout or b"") + (result.stderr or b"")
        return result.returncode == 0, output.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


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
        "session_start_time": status_data.get("session_start_time"),
        "version": status_data.get("version"),
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


def start_bot(progress=lambda msg: None):
    """Sveglia il PC Windows e avvia il bot.

    `progress(msg)` viene chiamato ad ogni passo importante: il chiamante
    decide cosa farne (mandarlo su Telegram, appenderlo al log della
    dashboard, ecc). Ritorna True se il bot risulta avviato.
    """
    progress("📡 Sveglio il PC Windows (Wake-on-LAN)...")
    send_magic_packet()
    time.sleep(WAKE_WAIT_SECONDS)

    for _ in range(WAKE_SSH_RETRIES):
        if windows_reachable():
            break
        time.sleep(WAKE_SSH_RETRY_DELAY)
    else:
        progress("❌ Il PC Windows non risponde via SSH dopo il Wake-on-LAN. Controlla che sia acceso.")
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


def stop_bot(progress=lambda msg: None):
    """Ferma il bot, chiude BlueStacks e spegne il PC Windows."""
    if not windows_reachable():
        progress("💤 PC Windows già spento o non raggiungibile, niente da fermare.")
        return False

    progress("⛔ Fermo il bot, chiudo BlueStacks e spengo il PC...")
    ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force"')
    ssh_run('powershell -Command "Get-Process -Name HD-Player -ErrorAction SilentlyContinue | Stop-Process -Force"')
    ssh_run("shutdown /s /t 5 /f")
    progress("✅ Fatto: bot fermato, BlueStacks chiuso, PC in spegnimento.")
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
