#!/usr/bin/env python3
"""Telegram polling bot that searches every field in the app's SQLite database."""
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "relevamiento.db"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {x.strip() for x in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if x.strip()}
API = f"https://api.telegram.org/bot{TOKEN}/"
MAX_TEXT = 3800
MAX_RESULTS = 12
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sistemarelevamiento_bot")


def normalize(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").casefold().strip()


def database_search(query):
    needle = normalize(query)
    matches = []
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.row_factory = sqlite3.Row
        categories = db.execute("SELECT id,name,fields FROM categories ORDER BY position").fetchall()
        for category in categories:
            fields = json.loads(category["fields"])
            records = db.execute("SELECT id,data FROM records WHERE category_id=? ORDER BY position,rowid", (category["id"],)).fetchall()
            for record in records:
                values = json.loads(record["data"])
                found = normalize(category["name"]).find(needle) >= 0
                if not found:
                    found = any(needle in normalize(values.get(field["key"])) for field in fields)
                if found:
                    matches.append((category["name"], fields, values))
    return matches


def format_record(category, fields, values, number):
    # Keep duplicate spreadsheet headers distinguishable in the answer.
    totals = {}
    for field in fields:
        totals[field["label"]] = totals.get(field["label"], 0) + 1
    seen = {}
    lines = [f"{number}. {category}"]
    for field in fields:
        value = values.get(field["key"])
        if value is None or str(value).strip() == "":
            continue
        label = field["label"]
        seen[label] = seen.get(label, 0) + 1
        if totals[label] > 1:
            label = f"{label} (campo {seen[label]})"
        lines.append(f"{label}: {str(value).strip()}")
    return "\n".join(lines)


def telegram(method, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(API + method, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Error de Telegram"))
    return result["result"]


def send(chat_id, message):
    telegram("sendMessage", {"chat_id": chat_id, "text": message[:MAX_TEXT], "disable_web_page_preview": True})


def answer(chat_id, text):
    text = (text or "").strip()
    if not text:
        send(chat_id, "Escribime un dato del equipo: serie, persona, modelo, ubicación u otro campo.")
        return
    try:
        matches = database_search(text)
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        log.exception("No se pudo consultar la base")
        send(chat_id, f"No pude consultar la base del relevamiento: {exc}")
        return
    if not matches:
        send(chat_id, "No encontré coincidencias en el relevamiento. Probá con otro dato o una parte más corta.")
        return
    total = len(matches)
    blocks = [format_record(category, fields, values, i + 1) for i, (category, fields, values) in enumerate(matches[:MAX_RESULTS])]
    header = f"Encontré {total} coincidencia(s):"
    if total > MAX_RESULTS:
        header += f"\nMuestro las primeras {MAX_RESULTS}; agregá más datos para acotar la búsqueda."
    message = header
    for block in blocks:
        candidate = message + "\n\n" + block
        if len(candidate) > MAX_TEXT and message != header:
            send(chat_id, message)
            message = block
        elif len(candidate) > MAX_TEXT:
            send(chat_id, header)
            message = block[:MAX_TEXT]
        else:
            message = candidate
    if message:
        send(chat_id, message)


def handle_message(message):
    chat = message.get("chat", {}).get("id")
    if chat is None:
        return
    if ALLOWED and str(chat) not in ALLOWED:
        send(chat, "Este bot no está habilitado para este chat.")
        return
    text = message.get("text", "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        send(chat, "¡Hola! Soy sistemarelevamiento_bot. Escribime cualquier dato de un equipo (serie, persona, modelo, ubicación, sistema operativo u otro campo) y te devuelvo los registros completos que coincidan. La búsqueda incluye todas las pestañas y se actualiza con lo que está guardado en el sitio.")
    elif text.startswith("/buscar"):
        answer(chat, text[len("/buscar"):])
    elif text.startswith("/"):
        send(chat, "Comandos: /start, /buscar dato. También podés escribirme directamente cualquier dato para buscarlo en todas las columnas.")
    else:
        answer(chat, text)


def main():
    if not TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN. Configuralo en las variables del Stack de Portainer.")
    if not DB_PATH.exists():
        raise SystemExit(f"No existe {DB_PATH}. El volumen debe ser el mismo que usa la app web.")
    log.info("Bot iniciado; base de datos: %s", DB_PATH)
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            updates = telegram("getUpdates?" + urllib.parse.urlencode(params), {})
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if message:
                    try:
                        handle_message(message)
                    except Exception:
                        log.exception("Error procesando mensaje")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            log.error("Telegram HTTP %s: %s", exc.code, detail[:500])
            time.sleep(10 if exc.code >= 500 else 30)
        except Exception:
            log.exception("Error en polling de Telegram")
            time.sleep(5)


if __name__ == "__main__":
    main()
