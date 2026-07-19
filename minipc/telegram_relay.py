#!/usr/bin/env python3
"""Relay Telegram che vive sul mini PC sempre acceso: ascolta comandi
/avvia, /stato, /stop e pilota il PC Windows (Wake-on-LAN + SSH) dove
gira davvero il bot di Clash of Clans. La logica di avvio/stato/stop
vera e propria e' in bot_control.py, condivisa con la dashboard web.

Solo libreria standard: nessuna dipendenza da installare.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

import bot_control

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    sys.exit(
        "Errore: variabili d'ambiente TELEGRAM_BOT_TOKEN e/o TELEGRAM_CHAT_ID mancanti.\n"
        "Crea ~/cred_relay (vedi minipc/cred_relay.example) prima di avviare il servizio."
    )

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

BTN_AVVIA = "▶️ Avvia"
BTN_STATO = "📊 Stato"
BTN_STOP = "⛔ Stop"

MENU_KEYBOARD = {
    "keyboard": [[BTN_AVVIA, BTN_STATO], [BTN_STOP]],
    "resize_keyboard": True,
    "is_persistent": True,
}


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
        tg_call("sendMessage", {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "reply_markup": MENU_KEYBOARD,
        })
    except Exception as e:
        print(f"[TELEGRAM] Errore invio messaggio: {e}")


def get_updates(offset, timeout=30):
    return tg_call("getUpdates", {"offset": offset, "timeout": timeout}, timeout=timeout + 10)


def cmd_avvia():
    bot_control.start_bot(progress=send_message)


def cmd_stato():
    status = bot_control.get_bot_status()
    if not status["windows_on"]:
        send_message("💤 PC Windows spento o non raggiungibile in rete.")
        return

    if status["running"]:
        log_tail = bot_control.get_log_tail(8)
        msg = (
            f"✅ PC Windows acceso, bot in esecuzione (attacco {status['trigger_count']}).\n\n"
            "Ultime righe di log:\n" + "\n".join(log_tail)
        )
    else:
        msg = "🟡 PC Windows acceso, ma il bot NON risulta in esecuzione."
    send_message(msg[:3500])


def cmd_stop():
    bot_control.stop_bot(progress=send_message)


COMMANDS = {
    "/avvia": cmd_avvia,
    "/start_bot": cmd_avvia,
    "/start": cmd_avvia,
    BTN_AVVIA: cmd_avvia,
    "/stato": cmd_stato,
    "/status": cmd_stato,
    BTN_STATO: cmd_stato,
    "/stop": cmd_stop,
    BTN_STOP: cmd_stop,
}


def handle_text(text):
    text = text.strip()
    cmd = text if text in COMMANDS else text.split()[0].lower()
    handler = COMMANDS.get(cmd)
    if handler:
        handler()
    elif cmd == "/help":
        send_message("Usa i pulsanti qui sotto, oppure:\n/avvia - sveglia il PC e avvia il bot\n/stato - controlla se sta girando\n/stop - ferma il bot")


# Controllo periodico che il bot non sia "sparito" senza che nessuno se ne
# accorga: se una sessione risultava in corso e il PC Windows smette
# improvvisamente di rispondere in rete (crash, riavvio inatteso, blackout),
# il bot stesso non puo' avvisare via Telegram perche' non c'e' piu'. Il
# relay, che vive sul mini PC sempre acceso, se ne accorge da fuori.
WATCHDOG_INTERVAL = 300  # secondi tra un controllo e l'altro
_watchdog_state = {"was_running": False, "alerted": False}


def check_watchdog():
    try:
        status = bot_control.get_bot_status()
    except Exception as e:
        print(f"[WATCHDOG] Errore controllo stato: {e}")
        return

    was_running = _watchdog_state["was_running"]
    now_running = bool(status.get("running"))
    windows_on = bool(status.get("windows_on"))

    if was_running and not now_running and not windows_on:
        if not _watchdog_state["alerted"]:
            send_message(
                "⚠️ Il PC Windows è sparito dalla rete mentre una sessione sembrava "
                "in corso (crash, riavvio inatteso o blackout?). Controlla di persona "
                "quando puoi — il bot non si è fermato da solo con il messaggio di fine sessione."
            )
            _watchdog_state["alerted"] = True
    else:
        _watchdog_state["alerted"] = False

    _watchdog_state["was_running"] = now_running


def main():
    print("[RELAY] Avviato, controllo backlog Telegram...")

    try:
        tg_call("setMyCommands", {"commands": [
            {"command": "avvia", "description": "Sveglia il PC e avvia il bot"},
            {"command": "stato", "description": "Controlla se il bot sta girando"},
            {"command": "stop", "description": "Ferma il bot"},
        ]})
    except Exception as e:
        print(f"[RELAY] Errore setMyCommands: {e}")

    offset = 0
    try:
        updates = get_updates(offset=0, timeout=1)
        for u in updates.get("result", []):
            offset = u["update_id"] + 1
    except Exception as e:
        print(f"[RELAY] Errore lettura backlog iniziale: {e}")

    print(f"[RELAY] Pronto, offset iniziale {offset}. In ascolto...")
    send_message("🤖 Relay pronto. Usa i pulsanti qui sotto.")

    last_watchdog_check = time.time()

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

            if time.time() - last_watchdog_check > WATCHDOG_INTERVAL:
                check_watchdog()
                last_watchdog_check = time.time()
        except urllib.error.URLError as e:
            print(f"[RELAY] Errore di rete, riprovo: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"[RELAY] Errore inatteso: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
