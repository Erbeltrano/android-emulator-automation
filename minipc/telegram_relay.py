#!/usr/bin/env python3
"""Relay Telegram che vive sul mini PC sempre acceso: ascolta comandi
/avvia, /stato, /stop e pilota il PC Windows (Wake-on-LAN + SSH) dove
gira davvero il bot di Clash of Clans.

Solo libreria standard: nessuna dipendenza da installare.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    sys.exit(
        "Errore: variabili d'ambiente TELEGRAM_BOT_TOKEN e/o TELEGRAM_CHAT_ID mancanti.\n"
        "Crea ~/cred_relay (vedi minipc/cred_relay.example) prima di avviare il servizio."
    )

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

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

WAKE_WAIT_SECONDS = 35   # attesa dopo il magic packet prima di provare SSH
WAKE_SSH_RETRIES = 10
WAKE_SSH_RETRY_DELAY = 5


def tg_call(method, params=None, timeout=35):
    url = f"{API_BASE}/{method}"
    data = None
    if params is not None:
        data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(text):
    try:
        tg_call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except Exception as e:
        print(f"[TELEGRAM] Errore invio messaggio: {e}")


def get_updates(offset, timeout=30):
    return tg_call("getUpdates", {"offset": offset, "timeout": timeout}, timeout=timeout + 10)


def send_magic_packet(mac):
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(packet, (WINDOWS_BROADCAST, 9))
    sock.sendto(packet, ("255.255.255.255", 9))
    sock.close()


def ssh_run(command, timeout=15):
    """Esegue un comando sul PC Windows via SSH. Ritorna (ok, stdout+stderr)."""
    full_cmd = ["ssh"] + SSH_OPTS + [f"{SSH_USER}@{WINDOWS_IP}", command]
    try:
        result = subprocess.run(full_cmd, capture_output=True, timeout=timeout, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def windows_reachable():
    ok, _ = ssh_run("echo ok", timeout=6)
    return ok


def cmd_avvia():
    send_message("📡 Sveglio il PC Windows (Wake-on-LAN)...")
    for _ in range(5):
        send_magic_packet(WINDOWS_MAC)
        time.sleep(1)
    time.sleep(WAKE_WAIT_SECONDS)

    for attempt in range(1, WAKE_SSH_RETRIES + 1):
        if windows_reachable():
            break
        time.sleep(WAKE_SSH_RETRY_DELAY)
    else:
        send_message("❌ Il PC Windows non risponde via SSH dopo il Wake-on-LAN. Controlla che sia acceso.")
        return

    ok, out = ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue"')
    if "python" in out.lower():
        send_message("ℹ️ Il bot risulta già in esecuzione sul PC Windows.")
        return

    ok, out = ssh_run('schtasks /run /tn "CoCBot"')
    if ok:
        send_message("✅ PC Windows sveglio, bot avviato. Riceverai a breve la notifica di avvio dal bot stesso.")
    else:
        send_message(f"⚠️ PC svegliato ma il lancio del task ha dato un problema:\n{out}")


def cmd_stato():
    if not windows_reachable():
        send_message("💤 PC Windows spento o non raggiungibile in rete.")
        return

    ok, out = ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Select Id,StartTime"')
    running = "python" not in out.lower() and out.strip() != "" and "Id" in out

    ok2, log_tail = ssh_run(
        'powershell -Command "Get-Content C:\\Users\\simon\\bot_log.txt -Tail 8 -ErrorAction SilentlyContinue"'
    )

    if running:
        msg = "✅ PC Windows acceso, bot in esecuzione.\n\nUltime righe di log:\n" + log_tail.strip()
    else:
        msg = "🟡 PC Windows acceso, ma il bot NON risulta in esecuzione."
    send_message(msg[:3500])


def cmd_stop():
    if not windows_reachable():
        send_message("💤 PC Windows già spento o non raggiungibile, niente da fermare.")
        return

    ssh_run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force"')
    send_message("⛔ Bot fermato sul PC Windows.")


COMMANDS = {
    "/avvia": cmd_avvia,
    "/start_bot": cmd_avvia,
    "/stato": cmd_stato,
    "/status": cmd_stato,
    "/stop": cmd_stop,
}


def handle_text(text):
    cmd = text.strip().split()[0].lower()
    handler = COMMANDS.get(cmd)
    if handler:
        handler()
    elif cmd == "/help":
        send_message("Comandi disponibili:\n/avvia - sveglia il PC e avvia il bot\n/stato - controlla se sta girando\n/stop - ferma il bot")


def main():
    print("[RELAY] Avviato, controllo backlog Telegram...")
    offset = 0
    try:
        updates = get_updates(offset=0, timeout=1)
        for u in updates.get("result", []):
            offset = u["update_id"] + 1
    except Exception as e:
        print(f"[RELAY] Errore lettura backlog iniziale: {e}")

    print(f"[RELAY] Pronto, offset iniziale {offset}. In ascolto...")

    while True:
        try:
            updates = get_updates(offset=offset)
            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message")
                if not msg:
                    continue
                chat_id = str(msg.get("chat", {}).get("id"))
                text = msg.get("text", "")
                if chat_id != TELEGRAM_CHAT_ID:
                    print(f"[RELAY] Ignorato messaggio da chat non autorizzata: {chat_id}")
                    continue
                if text:
                    print(f"[RELAY] Comando ricevuto: {text}")
                    handle_text(text)
        except urllib.error.URLError as e:
            print(f"[RELAY] Errore di rete, riprovo: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"[RELAY] Errore inatteso: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
