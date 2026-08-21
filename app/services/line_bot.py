"""
LINE Bot Service

Handles LINE Messaging API webhook events and reply logic.
LINE SDK v3 sends webhook events as dicts (not objects).
All event access uses dict-compatible helpers.
"""

import hashlib
import hmac
import base64
import requests
from app.config import Config


# ── Translation mode state (per-user) ─────────────────────────
# key = user_id, value = True (in translate mode)
TRANSLATE_MODE = {}


def _get_user_id(event) -> str:
    """Extract user ID from LINE event (dict or object format)."""
    src = event.get('source') or {}
    user_id = src.get('userId') or src.get('user_id', '')
    if user_id:
        return user_id
    group_id = src.get('groupId') or src.get('group_id', '')
    if group_id:
        return f"group:{group_id}"
    room_id = src.get('roomId') or src.get('room_id', '')
    if room_id:
        return f"room:{room_id}"
    return 'unknown'


def _get_message_text(event) -> str:
    """Extract text from message event (dict or object format)."""
    msg = event.get('message') or {}
    return (msg.get('text') or '').strip()


# ── Signature validation ──────────────────────────────────────

def validate_signature(body: bytes, signature: str) -> bool:
    """
    Validate the X-Line-Signature header against the request body.
    Returns True if valid, False otherwise.
    """
    if not Config.LINE_CHANNEL_SECRET:
        return True
    hash_obj = hmac.new(
        Config.LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    )
    expected = base64.b64encode(hash_obj.digest()).decode('utf-8')
    return hmac.compare_digest(expected, signature)


# ── Event handlers ─────────────────────────────────────────────

def handle_text_message(event) -> str | None:
    """
    Handle incoming text message events (LINE SDK v3 dict format).
    Returns the reply text, or None to skip replying.
    """
    text = _get_message_text(event)
    user_id = _get_user_id(event)

    # ── Translate mode ──────────────────────────────────
    if user_id in TRANSLATE_MODE:
        if text == '/translate end':
            del TRANSLATE_MODE[user_id]
            return "✅ 已離開翻譯模式。"
        lang = _detect_lang(text)
        if lang == 'vi':
            direction = 'vi-zh'
        elif lang == 'zh':
            direction = 'zh-vi'
        else:
            return (
                "⚠️ 無法判斷語言，請傳送中文或越南文。\n"
                "傳送 /translate end 結束翻譯模式。"
            )
        translated = _translate_via_llm(text, direction)
        return translated

    # ── /translate end ─────────────────────────────────
    if text == '/translate end':
        return "⚠️ 你目前不在翻譯模式中。"

    # ── /translate zh-vi or vi-zh ─────────────────────
    lowered = text.lower()
    if lowered.startswith('/translate '):
        return _handle_translate_start(text)

    # ── /status ────────────────────────────────────────
    if text == '/status':
        return _handle_status()

    # ── /help ──────────────────────────────────────────
    if text == '/help':
        return _handle_help()

    # ── /signal ─────────────────────────────────────────
    if text == '/signal':
        return _handle_signal()

    # ── /list ──────────────────────────────────────────
    if text == '/list':
        return _handle_list()

    # ── Unknown: general chat via LLM ────────────────────────────
    return _chat_via_llm(text)


def _chat_via_llm(user_text: str) -> str:
    """
    General chat using OpenRouter LLM.
    Acts as a friendly Vietnamese-Chinese bilingual assistant.
    """
    if not Config.OPENROUTER_API_KEY:
        return "⚠️ AI 服務尚未設定（缺少 API Key）。"

    system_prompt = (
        "你是一個友好、善於助人的越南翻譯助理，名叫 Vikki。"
        "你能流利地使用繁體中文和越南文。"
        "當用戶傳送中文時，你可以用越南文回答或翻譯；"
        "當用戶傳送越南文時，你可以用繁體中文回答或翻譯。"
        "同時也可以回答各種一般問題，保持簡潔、有禮貌、樂於助人。"
        "請只回覆有用的內容，不需要過多的修飾或解釋。"
    )

    try:
        response = requests.post(
            Config.OPENROUTER_API_URL,
            headers={
                'Authorization': f'Bearer {Config.OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://trading.thetainformation.com',
                'X-Title': 'Trading Signal Bot',
            },
            json={
                'model': Config.OPENROUTER_MODEL,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_text},
                ],
                'max_tokens': 500,
                'temperature': 0.7,
            },
            timeout=15,
        )
        if response.status_code == 200:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            if content:
                return content
        print(f"[Chat] LLM error: {response.status_code} - {response.text[:200]}")
        return "抱歉，我現在有點忙，請稍後再試。"
    except Exception as e:
        print(f"[Chat] Exception: {e}")
        return "抱歉，發生錯誤，請稍後再試。"


def handle_follow(event) -> str:
    """Handle LINE 'follow' (加好友) event."""
    return (
        "✅ 感謝加入！\n\n"
        "我是 TradingSys 機器人。\n"
        "可用指令：\n"
        "• /status    - 查看系統狀態\n"
        "• /signal    - 最新交易訊號\n"
        "• /list      - 顯示全部訊號記錄\n"
        "• /translate - 即時中越南翻譯\n"
        "• /help      - 顯示所有指令"
    )


def handle_unfollow(event) -> None:
    """Handle LINE 'unfollow' (封鎖) event."""
    src = event.get('source') or {}
    uid = src.get('userId') or 'unknown'
    print(f"[LINE] User unfollowed: {uid}")


def handle_join(event) -> str:
    """Handle LINE 'join' (被加入群組/聊天室) event."""
    return (
        "👋 TradingSys 機器人已上線！\n"
        "目前使用 /signal 查看最新訊號。"
    )


def handle_leave(event) -> None:
    """Handle LINE 'leave' (被踢出群組) event."""
    src = event.get('source') or {}
    gid = src.get('groupId') or src.get('roomId') or 'unknown'
    print(f"[LINE] Bot left: {gid}")


# ── Command implementations ─────────────────────────────────

def _handle_status() -> str:
    from app.models import get_latest_signal
    latest = get_latest_signal()
    if not latest:
        return "⚠️ 目前資料庫中沒有任何訊號記錄。"
    sym = latest.get('symbol', 'N/A')
    rec = latest.get('recommendation', '無')
    strength = latest.get('signal_strength', '無')
    price = latest.get('price', 'N/A')
    ts = latest.get('received_at', 'N/A')
    emoji = "🟢" if rec == "做多" else ("🔴" if rec == "做空" else "⚪")
    return (
        f"📊 TradingSys 狀態\n"
        f"━━━━━━━━━━━━━━━\n"
        f"最新訊號：{emoji} {sym}\n"
        f"價格：{price}\n"
        f"建議：{rec}（{strength}）\n"
        f"時間：{ts[:19] if ts else 'N/A'}"
    )


def _handle_help() -> str:
    return (
        "📖 TradingSys 指令列表\n"
        "━━━━━━━━━━━━━━━\n"
        "/status    - 查看系統狀態與最新訊號\n"
        "/signal    - 最新交易訊號詳情\n"
        "/list      - 顯示全部訊號記錄\n"
        "/translate - 即時中越南翻譯\n"
        "/help      - 顯示此訊息"
    )


def _handle_signal() -> str:
    from app.models import get_latest_signal
    latest = get_latest_signal()
    if not latest:
        return "⚠️ 目前沒有任何訊號記錄。"

    sym = latest.get('symbol', 'N/A')
    price = latest.get('price', 'N/A')
    rec = latest.get('recommendation', '無')
    strength = latest.get('signal_strength', '無')
    emoji = "🟢" if rec == "做多" else ("🔴" if rec == "做空" else "⚪")
    strength_ico = {"建議": "📊", "積極": "📈", "強烈": "🚨"}.get(strength, "📊")
    durations = {"建議": "約1-2小時", "積極": "約4-8小時", "強烈": "約1天至數日"}
    duration = durations.get(strength, "")

    return (
        f"{emoji} 期貨訊號\n"
        f"━━━━━━━━━━━━━━━\n"
        f"標的：{sym}\n"
        f"價格：{price}\n"
        f"建議：{rec} {strength_ico} {strength}\n"
        f"預計持續：{duration}\n\n"
        f"僅供參考，請自行判斷風險"
    )


def _handle_list() -> str:
    from app.models import get_all_signals
    signals = get_all_signals()
    if not signals:
        return "⚠️ 目前沒有任何訊號記錄。"

    # LINE 單則文字訊息上限為 5000 字元；超出時安全截斷，避免整則被拒。
    LINE_TEXT_LIMIT = 4800

    lines = [f"📋 全部訊號（{len(signals)}筆）", "━━━━━━━━━━━━━━━"]
    truncated = 0
    for i, r in enumerate(signals, 1):
        sym = r.get('symbol', '?')
        rec = r.get('recommendation', '無')
        strength = r.get('signal_strength', '無')
        ts = r.get('received_at', '')[:10]
        emoji = "🟢" if rec == "做多" else ("🔴" if rec == "做空" else "⚪")
        line = f"{i}. {emoji} {sym} | {rec}（{strength}）| {ts}"
        if len("\n".join(lines)) + len(line) + 1 > LINE_TEXT_LIMIT:
            truncated = len(signals) - (i - 1)
            break
        lines.append(line)

    if truncated:
        lines.append(f"⋯ 其餘 {truncated} 筆因 LINE 訊息長度上限未顯示")

    return "\n".join(lines)


# ── Translation ──────────────────────────────────────────────

VIETNAMESE_CHARS = 'àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũọưừứửữựỳýỷỹỵđ'
VIETNAMESE_SET = set(VIETNAMESE_CHARS)


def _is_vietnamese(text: str) -> bool:
    text_lower = text.lower()
    vn_chars = sum(1 for c in text_lower if c in VIETNAMESE_SET)
    vn_patterns = ['nh', 'ng', 'kh', 'th', 'ph', 'tr', 'ch', 'gi', 'qu',
                   'ấ', 'ắ', 'ư', 'ơ', 'ê', 'ô', 'ă', 'đ']
    vn_count = sum(1 for p in vn_patterns if p in text_lower)
    return vn_chars >= 2 or vn_count >= 2


def _detect_lang(text: str) -> str:
    if _is_vietnamese(text):
        return 'vi'
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_count > len(text) * 0.3 or cjk_count > 3:
        return 'zh'
    return 'unknown'


def _handle_translate_start(text: str) -> str:
    content = text[len('/translate'):].strip().lower()
    parts = content.split(' ', 1)

    if parts[0] not in ('zh-vi', 'vi-zh'):
        return (
            "⚠️ 格式錯誤。翻譯模式進入方式：\n"
            "━━━━━━━━━━━━━━━\n"
            "/translate zh-vi  或  /translate vi-zh\n"
            "→ 進入中越南翻譯模式\n\n"
            "💡 直接傳送文字即可翻譯。\n"
            "📌 傳送 /translate end 結束翻譯模式。"
        )

    return (
        "🌐 已進入翻譯模式\n"
        "━━━━━━━━━━━━━━━\n"
        "收到中文 → 翻譯成越南文\n"
        "收到越南文 → 翻譯成中文\n\n"
        "💡 直接傳送文字即可翻譯。\n"
        "📌 傳送 /translate end 結束翻譯模式。"
    )


def _enter_translate_mode(user_id: str) -> None:
    TRANSLATE_MODE[user_id] = True


def _translate_via_llm(text: str, direction: str) -> str:
    if not Config.OPENROUTER_API_KEY:
        return "⚠️ 翻譯服務尚未設定（缺少 API Key）。"

    system_prompt = (
        "You are a professional translator. Translate the following text accurately and naturally. "
        "Only output the translated text, nothing else. No explanations, no quotes."
    )
    if direction == 'zh-vi':
        user_prompt = f"Translate the following Chinese text to Vietnamese:\n{text}"
    else:
        user_prompt = f"Translate the following Vietnamese text to Chinese (Simplified):\n{text}"

    try:
        response = requests.post(
            Config.OPENROUTER_API_URL,
            headers={
                'Authorization': f'Bearer {Config.OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://trading.thetainformation.com',
                'X-Title': 'Trading Signal Bot',
            },
            json={
                'model': Config.OPENROUTER_MODEL,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'max_tokens': 500,
                'temperature': 0.3,
            },
            timeout=15,
        )
        if response.status_code == 200:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            if content:
                return content
        print(f"[Translate] LLM error: {response.status_code} - {response.text[:200]}")
        return "⚠️ 翻譯服務暫時無法使用，請稍後再試。"
    except Exception as e:
        print(f"[Translate] Exception: {e}")
        return "⚠️ 翻譯服務發生錯誤，請稍後再試。"
