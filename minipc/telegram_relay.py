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
import tempfile
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
BTN_SCHERMO = "📸 Schermo"
BTN_MENU = "🔙 Menu principale"
BTN_VILLAGGIO_PRIMARIO = "🏠 Villaggio Principale"
BTN_VILLAGGIO_SECONDARIO = "🏗️ Villaggio Secondario"
BTN_MURA_TOGGLE = "🧱 Mura ON/OFF"

TOP_MENU_KEYBOARD = {
    "keyboard": [[BTN_VILLAGGIO_PRIMARIO], [BTN_VILLAGGIO_SECONDARIO]],
    "resize_keyboard": True,
    "is_persistent": True,
}

VILLAGE_KEYBOARD = {
    "keyboard": [[BTN_AVVIA, BTN_STATO], [BTN_STOP, BTN_SCHERMO], [BTN_MURA_TOGGLE], [BTN_MENU]],
    "resize_keyboard": True,
    "is_persistent": True,
}

# Un solo utente autorizzato (controllato su TELEGRAM_CHAT_ID), quindi basta
# uno stato in memoria condiviso per sapere su quale villaggio stanno
# operando i pulsanti "Avvia/Stato/Stop/Schermo" - si azzera su "primario"
# ad ogni riavvio del relay. Il bot del villaggio secondario non esiste
# ancora (vedi secondo_villaggio/): i comandi restano gia' pronti nel menu,
# per ora rispondono solo con un avviso invece di fare qualcosa.
_state = {"village": "primario"}


def tg_call(method, params=None, timeout=35):
    url = f"{API_BASE}/{method}"
    data = None
    if params is not None:
        data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(text, keyboard=None):
    """`keyboard=None` mostra la tastiera del villaggio corrente (il caso
    comune: risposta a un comando avvia/stato/stop/schermo) - si passa
    esplicitamente TOP_MENU_KEYBOARD solo quando si torna al menu di scelta
    villaggio.
    """
    if keyboard is None:
        keyboard = VILLAGE_KEYBOARD
    try:
        tg_call("sendMessage", {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "reply_markup": keyboard,
        })
    except Exception as e:
        print(f"[TELEGRAM] Errore invio messaggio: {e}")


def get_updates(offset, timeout=30):
    return tg_call("getUpdates", {"offset": offset, "timeout": timeout}, timeout=timeout + 10)


def send_photo(image_path):
    """Manda una foto locale come messaggio Telegram (multipart/form-data
    costruito a mano: niente librerie esterne, solo urllib).
    """
    boundary = f"----coc-bot-{int(time.time() * 1000)}"
    with open(image_path, "rb") as f:
        image_data = f.read()

    def field(name, value):
        return (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        ).encode("utf-8")

    body = field("chat_id", TELEGRAM_CHAT_ID)
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"screen.png\"\r\n"
        "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8")
    body += image_data
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_villaggio_primario():
    _state["village"] = "primario"
    send_message("🏠 Villaggio Principale selezionato.")


def cmd_villaggio_secondario():
    _state["village"] = "secondario"
    send_message(
        "🏗️ Villaggio Secondario selezionato.\n"
        "Attacco (doppio raid) fino a una sessione di 28-34 cicli scelta a "
        "caso, raccolta elisir ogni 5 cicli (e all'ultimo della sessione) - "
        "tutto automatico. Upgrade mura disattivato (v0.31, non si "
        "comportava bene in produzione)."
    )


def cmd_menu():
    send_message("Scegli un villaggio:", keyboard=TOP_MENU_KEYBOARD)


def cmd_avvia():
    if _state["village"] == "secondario":
        bot_control.start_bot_costruttori(progress=send_message)
        return
    bot_control.start_bot(progress=send_message)


def cmd_stato():
    if _state["village"] == "secondario":
        status = bot_control.get_bot_status()
        if not status["windows_on"]:
            send_message("💤 PC Windows spento o non raggiungibile in rete.")
            return
        if status["running"]:
            log_tail = bot_control.get_costruttori_log_tail(8)
            msg = (
                "✅ PC Windows acceso, bot Villaggio Costruttori in esecuzione.\n\n"
                "Ultime righe di log:\n" + "\n".join(log_tail)
            )
        else:
            msg = "🟡 PC Windows acceso, ma il bot NON risulta in esecuzione."
        send_message(msg[:3500])
        return

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
    # Generico per entrambi i villaggi: stop_bot() ferma qualunque processo
    # python.exe in esecuzione (primario o Villaggio Costruttori, si
    # escludono a vicenda) + BlueStacks + spegne il PC.
    bot_control.stop_bot(progress=send_message)


def cmd_muraon():
    settings = bot_control.get_settings()
    settings["auto_wall_upgrade"] = True
    bot_control.save_settings(settings)
    send_message("✅ Upgrade automatico mura attivato: a fine sessione, se c'è un costruttore libero, le risorse farmate andranno a potenziare le mura.")


def cmd_muraoff():
    settings = bot_control.get_settings()
    settings["auto_wall_upgrade"] = False
    bot_control.save_settings(settings)
    send_message("⛔ Upgrade automatico mura disattivato.")


def cmd_mura_toggle():
    """Bottone unico che alterna lo stato invece di due comandi separati
    (/muraon, /muraoff restano comunque disponibili per chi preferisce
    il testo). Non ha senso per il villaggio secondario: quel bot ha un
    proprio upgrade mura interno (WALL_UPGRADE_ENABLED in
    bot_costruttori.py), non collegato a queste impostazioni - e da v0.31
    è disattivato del tutto (non si comportava bene in produzione).
    """
    if _state["village"] == "secondario":
        send_message("🚧 Il Villaggio Secondario ha l'upgrade mura disattivato (v0.31, non si comportava bene in produzione) - non ancora attivabile da qui.")
        return
    settings = bot_control.get_settings()
    settings["auto_wall_upgrade"] = not settings.get("auto_wall_upgrade", False)
    bot_control.save_settings(settings)
    if settings["auto_wall_upgrade"]:
        send_message("✅ Upgrade automatico mura attivato: a fine sessione, se c'è un costruttore libero, le risorse farmate andranno a potenziare le mura.")
    else:
        send_message("⛔ Upgrade automatico mura disattivato.")


def cmd_pausaesame():
    """Ferma tutto cio' che potrebbe essere visto da un software di
    proctoring (es. Respondus LockDown Browser) durante un esame fatto sullo
    stesso PC Windows che fa girare il bot - richiesta esplicita dell'utente
    (2026-09-01), per poterlo rifare da solo ad ogni esame durante l'anno
    senza dover chiedere a me ogni volta. Chiama pause_for_exam() (gia'
    esistente in bot_control.py dal 2026-08-12, prima azionabile solo a
    mano): ferma bot/BlueStacks/componenti in background, disabilita i task
    pianificati, rimuove la voce di registro di riavvio automatico. NON
    tocca il server SSH (vedi nota in bot_control.py): disattivarlo da qui
    taglierebbe anche questo stesso comando fuori dal PC, rendendo
    impossibile un /riprendiesame remoto - quel pezzo resta un'azione
    manuale locale sul PC Windows (script dedicato, vedi windows/).
    """
    bot_control.pause_for_exam(progress=send_message)


def cmd_riprendiesame():
    bot_control.resume_after_exam(progress=send_message)


def cmd_schermo():
    tmp_path = os.path.join(tempfile.gettempdir(), "coc_screen_relay.png")
    ok, err = bot_control.capture_screen(tmp_path)
    if not ok:
        send_message(f"❌ Impossibile catturare lo schermo: {err}")
        return
    try:
        send_photo(tmp_path)
    except Exception as e:
        send_message(f"❌ Screenshot catturato ma invio a Telegram fallito: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


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
    "/muraon": cmd_muraon,
    "/muraoff": cmd_muraoff,
    BTN_MURA_TOGGLE: cmd_mura_toggle,
    "/pausaesame": cmd_pausaesame,
    "/riprendiesame": cmd_riprendiesame,
    "/schermo": cmd_schermo,
    BTN_SCHERMO: cmd_schermo,
    "/menu": cmd_menu,
    BTN_MENU: cmd_menu,
    "/villaggio1": cmd_villaggio_primario,
    BTN_VILLAGGIO_PRIMARIO: cmd_villaggio_primario,
    "/villaggio2": cmd_villaggio_secondario,
    BTN_VILLAGGIO_SECONDARIO: cmd_villaggio_secondario,
}


def handle_text(text):
    text = text.strip()
    cmd = text if text in COMMANDS else text.split()[0].lower()
    handler = COMMANDS.get(cmd)
    if handler:
        handler()
    elif cmd == "/help":
        send_message(
            "Usa i pulsanti qui sotto, oppure:\n"
            "/menu - torna alla scelta villaggio\n"
            "/villaggio1 - passa al Villaggio Principale\n"
            "/villaggio2 - passa al Villaggio Secondario\n"
            "/avvia - sveglia il PC e avvia il bot (del villaggio scelto)\n"
            "/stato - controlla se sta girando\n"
            "/stop - ferma il bot\n"
            "/schermo - manda uno screenshot dell'emulatore\n"
            "/muraon - attiva l'upgrade automatico mura a fine sessione\n"
            "/muraoff - disattiva l'upgrade automatico mura\n"
            "(oppure usa il bottone 🧱 Mura ON/OFF, alterna lo stato attuale)\n"
            "/pausaesame - ferma tutto (bot, BlueStacks, avvio automatico) per un esame con proctoring\n"
            "/riprendiesame - riattiva tutto dopo l'esame\n"
            "(SSH non viene toccato da questi due comandi - vedi windows/ per lo script locale)"
        )


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
            {"command": "menu", "description": "Torna alla scelta villaggio"},
            {"command": "villaggio1", "description": "Passa al Villaggio Principale"},
            {"command": "villaggio2", "description": "Passa al Villaggio Secondario"},
            {"command": "avvia", "description": "Sveglia il PC e avvia il bot"},
            {"command": "stato", "description": "Controlla se il bot sta girando"},
            {"command": "stop", "description": "Ferma il bot"},
            {"command": "schermo", "description": "Manda uno screenshot dell'emulatore"},
            {"command": "muraon", "description": "Attiva l'upgrade automatico mura a fine sessione"},
            {"command": "muraoff", "description": "Disattiva l'upgrade automatico mura"},
            {"command": "pausaesame", "description": "Ferma tutto per un esame con proctoring"},
            {"command": "riprendiesame", "description": "Riattiva tutto dopo l'esame"},
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
    _state["village"] = "primario"
    send_message("🤖 Relay pronto. Scegli un villaggio:", keyboard=TOP_MENU_KEYBOARD)

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
