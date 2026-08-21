"""Long-poll the secondary Telegram bot for /start registrations."""
from __future__ import annotations

import threading
import time
import requests
from app.config import Config
from app.telegram_subscribers import register_subscriber, unregister_subscriber

_started = False


def _handle_update(update: dict) -> None:
    message = update.get('message') or {}
    chat = message.get('chat') or {}
    user = message.get('from') or {}
    if chat.get('type') != 'private' or not chat.get('id'):
        return
    text = (message.get('text') or '').strip().lower()
    if text.startswith('/start'):
        register_subscriber(chat['id'], user)
        _send(chat['id'], '已完成測試訊號訂閱。提醒：此為測試功能,不可用於實際投資。')
    elif text.startswith('/stop'):
        unregister_subscriber(chat['id'])
        _send(chat['id'], '已停止接收測試訊號。')


def _send(chat_id, text: str) -> None:
    token = Config.TELEGRAM_BOT_TOKEN_2
    if not token:
        return
    try:
        requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                      json={'chat_id': chat_id, 'text': '[此為測試功能,不可用於實際投資]\n\n' + text}, timeout=10)
    except Exception as exc:
        print(f'[Telegram-Secondary-Polling] reply error: {exc}', flush=True)


def _run() -> None:
    token = Config.TELEGRAM_BOT_TOKEN_2
    offset = None
    while True:
        try:
            params = {'timeout': 25}
            if offset is not None:
                params['offset'] = offset
            response = requests.get(f'https://api.telegram.org/bot{token}/getUpdates', params=params, timeout=35)
            result = response.json()
            for update in result.get('result', []):
                offset = update['update_id'] + 1
                _handle_update(update)
        except Exception as exc:
            print(f'[Telegram-Secondary-Polling] error: {exc}', flush=True)
            time.sleep(5)


def start_polling() -> None:
    global _started
    if _started or not Config.TELEGRAM_BOT_TOKEN_2:
        return
    _started = True
    threading.Thread(target=_run, name='telegram-secondary-polling', daemon=True).start()
    print('[Telegram-Secondary-Polling] started', flush=True)
