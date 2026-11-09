"""Telegram delivery. Needs secret TELEGRAM_BOT_TOKEN; finds the chat id itself on first run."""
import json
import os
import urllib.parse
import urllib.request

CHAT_FILE = os.path.join("data", "telegram_chat.json")


def _call(token, method, **params):
    data = urllib.parse.urlencode(params).encode() if params else None
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def chat_id(token):
    env = os.environ.get("TELEGRAM_CHAT_ID")
    if env:
        return env
    if os.path.exists(CHAT_FILE):
        with open(CHAT_FILE) as fh:
            return json.load(fh)["chat_id"]
    upd = _call(token, "getUpdates").get("result", [])
    for u in reversed(upd):
        msg = u.get("message") or u.get("edited_message") or {}
        if msg.get("chat", {}).get("type") == "private":
            cid = msg["chat"]["id"]
            os.makedirs("data", exist_ok=True)
            with open(CHAT_FILE, "w") as fh:
                json.dump({"chat_id": cid}, fh)
            return cid
    return None


def send(text, log):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log("Telegram: no TELEGRAM_BOT_TOKEN secret, skipped")
        return
    try:
        cid = chat_id(token)
        if not cid:
            log("Telegram: no chat found. Open your bot and send it 'hi', then re-run.")
            return
        if len(text) > 4000:
            text = text[:3990] + "\n…"
        _call(token, "sendMessage", chat_id=cid, text=text, parse_mode="HTML", disable_web_page_preview="true")
        log("Telegram: sent")
    except Exception as e:  # never fail the run over a notification
        log(f"Telegram failed: {e}")
