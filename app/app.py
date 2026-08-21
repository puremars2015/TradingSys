"""
TradingView Signal Bot - Flask Application

Receives TradingView webhook data (KD 1H/4H/1D + SMA10/60/120/720 的數值陣列),
analyzes it, and sends notifications via Telegram.
Also exposes a LINE Bot webhook endpoint.
"""

import json
from datetime import datetime, timezone
from threading import Thread
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, Response
from app.config import Config
from app.models import init_db, get_latest_signal, get_recent_signals
from app.services.signal_analyzer import parse_payload, process_signal
from app.services.telegram_bot import send_trading_notification
from app.telegram_polling import start_polling
from app.services.llm_generator import generate_recommendation_message


def create_app():
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize database on startup
    init_db()
    start_polling()
    
    return app


app = create_app()


@app.template_filter('taiwan_time')
def format_taiwan_time(value):
    """將資料庫時間固定轉成台灣時間（GMT+8）顯示。"""
    if not value:
        return 'N/A'
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return str(value)[:19]


@app.route('/')
def index():
    """Home page showing recent signals"""
    healthy = False
    db_records = 0
    try:
        recent = get_recent_signals(limit=5)
        latest = get_latest_signal()
        db_records = len(recent)
        healthy = True
    except Exception as e:
        recent = []
        latest = None
        print(f"[Health Check] DB error: {e}")

    return render_template(
        'index.html',
        recent_signals=recent,
        latest_signal=latest,
        healthy=healthy,
        db_records=db_records
    )


@app.route('/api/status')
def status():
    """Health check endpoint"""
    latest = get_latest_signal()
    return jsonify({
        'status': 'ok',
        'service': 'TradingView Signal Bot',
        'latest_signal': latest is not None,
        'database': Config.DATABASE_PATH
    })


def _async_notify(data: dict, result: dict):
    """
    Background thread: sends the Telegram notification.
    Runs after the webhook has already returned 200 to TradingView.
    """
    try:
        message = None
        if result['should_notify']:
            message = generate_recommendation_message(
                symbol=data.get('symbol'),
                price=data.get('price'),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {}),
                sma_data=data.get('sma', {}),
                trigger=result.get('trigger')
            )
        send_trading_notification(
            symbol=data.get('symbol'),
            price=data.get('price'),
            recommendation=result['recommendation'],
            signal_strength=result['signal_strength'],
            kd_data=data.get('kd', {}),
            secondary_message=message,
            send_secondary=result['should_notify'],
            sma_data=data.get('sma', {}),
            trigger=result.get('trigger')
        )
    except Exception as e:
        print(f"[Async Notify] error: {e}")


def _extract_values(payload):
    """從 request body 取出數值陣列，允許裸陣列或 {"values": [...]} 兩種包法。"""
    if isinstance(payload, dict):
        for key in ('values', 'data', 'payload'):
            if key in payload:
                return payload[key]
        return None
    return payload


@app.route('/webhook/kd-sma', methods=['POST'])
def webhook_kd_sma():
    """
    Receive TradingView alert as a plain numeric array:

        [SMA10, SMA60, SMA120, SMA720, K1H, D1H, K4H, D4H, K1D, D1D, PRICE]

    商品代號固定為 Config.DEFAULT_SYMBOL，可用 ?symbol=XXX 覆寫。
    """
    try:
        payload = request.get_json(silent=True, force=True)
        if payload is None:
            body = request.get_data(as_text=True) or ''
            try:
                payload = json.loads(body)
            except ValueError:
                print(f"[Webhook kd-sma] Unparseable body: {body[:200]}")
                return jsonify({'error': 'Invalid JSON payload'}), 400

        values = _extract_values(payload)
        try:
            data = parse_payload(values, symbol=request.args.get('symbol'))
        except ValueError as e:
            print(f"[Webhook kd-sma] Bad payload: {e} / raw={payload}")
            return jsonify({'error': str(e)}), 400

        result = process_signal(data)
        Thread(target=_async_notify, args=(data, result), daemon=True).start()

        return jsonify({
            'success': True,
            'signal_id': result['row_id'],
            'symbol': data['symbol'],
            'recommendation': result['recommendation'],
            'signal_strength': result['signal_strength'],
            'trigger': result['trigger'],
            'notified': result['should_notify'],
            'deduped': result.get('deduped', False)
        })
    except Exception as e:
        print(f"[Webhook kd-sma] Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ── LINE Bot webhook ──────────────────────────────────────────────

@app.route('/line-webhook', methods=['POST'])
def line_webhook():
    """
    LINE Messaging API webhook endpoint.
    """
    from app.services.line_bot import (
        validate_signature,
        handle_text_message,
        handle_follow,
        handle_unfollow,
        handle_join,
        handle_leave,
        _get_user_id,
        _enter_translate_mode,
    )

    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data()

    if not validate_signature(body, signature):
        print("[LINE Webhook] Invalid signature")
        return jsonify({'error': 'Invalid signature'}), 400

    try:
        payload = request.get_json()
    except Exception:
        payload = {}

    if not payload or 'events' not in payload:
        # LINE webhook verification — must echo the challenge field
        if 'challenge' in payload:
            print(f"[LINE Webhook] Verification challenge: {payload['challenge']}")
            return jsonify({'challenge': payload['challenge']}), 200
        return '', 200

    reply_events = []

    for event in payload.get('events', []):
        event_type = event.get('type', '')
        reply_token = event.get('replyToken', '')
        print(f"[LINE Webhook] Event: {event_type}")

        reply_text = None

        try:
            if event_type == 'message':
                msg_type = event.get('message', {}).get('type', '')
                if msg_type == 'text':
                    raw_text = (event.get('message') or {}).get('text', '') or ''
                    lowered = raw_text.lower().strip()
                    # Check for /translate zh-vi or vi-zh FIRST (before handle_text_message)
                    # so we DON'T enter translate mode and then re-process the same message
                    is_translate_cmd = (
                        lowered == '/translate zh-vi' or
                        lowered == '/translate vi-zh'
                    )
                    reply_text = handle_text_message(event)
                    # AFTER handle_text_message returns, if it was a translate start command,
                    # enter translate mode (so the *next* message triggers translate, not this one)
                    if is_translate_cmd:
                        user_id = _get_user_id(event)
                        _enter_translate_mode(user_id)
                        print(f"[LINE] User {user_id} entered translate mode")

            elif event_type == 'follow':
                reply_text = handle_follow(event)

            elif event_type == 'unfollow':
                handle_unfollow(event)

            elif event_type in ('join', 'group_join', 'room_join'):
                reply_text = handle_join(event)

            elif event_type in ('leave', 'leave'):
                handle_leave(event)

        except Exception as e:
            print(f"[LINE Webhook] Handler error: {e}")
            reply_text = "⚠️ 處理訊息時發生錯誤，請稍後再試。"

        if reply_text and reply_token:
            reply_events.append((reply_token, reply_text))

    # Send replies using LINE Messaging API v2
    if reply_events:
        try:
            import requests as _req
            _url = 'https://api.line.me/v2/bot/message/reply'
            _headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {Config.LINE_CHANNEL_ACCESS_TOKEN}',
            }
            for token, text in reply_events:
                _payload = {
                    'replyToken': token,
                    'messages': [{'type': 'text', 'text': text}],
                }
                _r = _req.post(_url, headers=_headers, json=_payload, timeout=10)
                if _r.status_code == 200:
                    print(f"[LINE Webhook] Replied OK: {text[:50]}")
                else:
                    print(f"[LINE Webhook] Reply failed { _r.status_code}: {_r.text[:200]}")
        except Exception as e:
            print(f"[LINE Webhook] Reply error: {type(e).__name__}: {e}")

    return '', 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=Config.DEBUG)
