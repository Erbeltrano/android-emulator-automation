#!/usr/bin/env python3
"""Dashboard web per il bot CoC: pagina con Avvia/Stop, statistiche in
tempo reale e log live, leggendo tutto dal PC Windows via SSH
(bot_control.py, condiviso col relay Telegram). Pensata per essere
raggiunta solo dalla rete di casa (nessuna esposizione su internet).

Solo libreria standard: nessuna dipendenza da installare.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bot_control

HOST = "0.0.0.0"
PORT = 8090
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_lock = threading.Lock()
_action_message = ""
_action_running = False


def _set_action_message(msg):
    global _action_message
    with _lock:
        _action_message = msg
    print(f"[DASHBOARD] {msg}")


def _run_start():
    global _action_running
    with _lock:
        if _action_running:
            return
        _action_running = True
    try:
        bot_control.start_bot(progress=_set_action_message)
    finally:
        with _lock:
            _action_running = False


def _run_stop():
    global _action_running
    with _lock:
        if _action_running:
            return
        _action_running = True
    try:
        bot_control.stop_bot(progress=_set_action_message)
    finally:
        with _lock:
            _action_running = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silenzia i log di accesso di default di http.server

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filename, content_type):
        path = os.path.join(STATIC_DIR, filename)
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif self.path == "/api/status":
            status = bot_control.get_bot_status()
            with _lock:
                status["action_message"] = _action_message
                status["action_running"] = _action_running
            self._send_json(status)
        elif self.path == "/api/log":
            self._send_json({"lines": bot_control.get_log_tail(40)})
        elif self.path == "/api/settings":
            self._send_json(bot_control.get_settings())
        elif self.path == "/api/history":
            self._send_json({"sessions": bot_control.get_history(20)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/start":
            with _lock:
                busy = _action_running
            if busy:
                self._send_json({"ok": False, "message": "Operazione già in corso"})
                return
            threading.Thread(target=_run_start, daemon=True).start()
            self._send_json({"ok": True})
        elif self.path == "/api/stop":
            with _lock:
                busy = _action_running
            if busy:
                self._send_json({"ok": False, "message": "Operazione già in corso"})
                return
            threading.Thread(target=_run_stop, daemon=True).start()
            self._send_json({"ok": True})
        elif self.path == "/api/settings":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                new_settings = json.loads(body)
            except ValueError:
                self._send_json({"ok": False, "message": "JSON non valido"}, status=400)
                return
            ok = bot_control.save_settings(new_settings)
            self._send_json({"ok": ok})
        else:
            self.send_response(404)
            self.end_headers()


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[DASHBOARD] In ascolto su http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
