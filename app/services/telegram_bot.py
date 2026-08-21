"""
Telegram Bot Service

Sends trading recommendations to users via Telegram bot.
"""

import html
import requests
from app.config import Config
from app.telegram_subscribers import get_subscriber_chat_ids

TEST_WARNING_PREFIX = '[此為測試功能,不可用於實際投資]\n\n'


def _send_telegram_message_via_bot(message: str, bot_token: str, user_id: str, label: str = 'Telegram') -> bool:
    """Send one Telegram message through a specific bot/user pair."""
    if not bot_token or bot_token == 'your-bot-token':
        print(f"[{label}] Bot token not configured. Message: {message[:100]}...")
        return False

    if not user_id:
        print(f"[{label}] User ID not configured.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # AI 內容是純文字，但 Telegram 使用 HTML parse mode。若 AI 回傳
    # 「SMA10<60」等比較符號，未跳脫會讓 Telegram 拒收整則訊息。
    message = TEST_WARNING_PREFIX + message
    safe_message = html.escape(message, quote=False) if label == 'Telegram-Secondary' else message
    payload = {
        'chat_id': user_id,
        'text': safe_message,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()

        if result.get('ok'):
            print(f"[{label}] Message sent successfully (message_id={result.get('result', {}).get('message_id')})", flush=True)
            return True
        else:
            print(f"[{label}] Error: HTTP {response.status_code}; {result.get('description')}", flush=True)
            return False
    except Exception as e:
        print(f"[{label}] Exception: {str(e)}", flush=True)
        return False


def send_telegram_message(message: str, secondary_message: str | None = None,
                          send_secondary: bool = True) -> bool:
    """
    Send message to primary Telegram user and optionally to a second bot/user.

    - Primary bot always receives `message`
    - Secondary bot receives `secondary_message` if provided, otherwise falls back to `message`
    - `send_secondary=False` sends only through the primary bot

    Returns True if at least one configured send succeeds.
    """
    results = []

    primary_result = _send_telegram_message_via_bot(
        message,
        Config.TELEGRAM_BOT_TOKEN,
        Config.TELEGRAM_USER_ID,
        'Telegram-Primary'
    )
    results.append(primary_result)

    if send_secondary and Config.TELEGRAM_BOT_TOKEN_2:
        secondary_message = secondary_message if secondary_message else message
        for chat_id in get_subscriber_chat_ids():
            secondary_result = _send_telegram_message_via_bot(
                secondary_message, Config.TELEGRAM_BOT_TOKEN_2, chat_id,
                'Telegram-Secondary'
            )
            results.append(secondary_result)

    return any(results)


DIRECTION_EMOJI = {'做多': '🟢', '做空': '🔴', '持有': '🟡'}
STRENGTH_EMOJI = {'建議': '📊', '積極': '📈', '強烈': '🚨', '持續': '⏳'}

# 顯示用的均線與週期標籤（皆為 1H 週期計算）
SMA_LABELS = (('sma10', 'SMA10'), ('sma60', 'SMA60'), ('sma120', 'SMA120'), ('sma720', 'SMA720'))
KD_LABELS = (('1h', '1H'), ('4h', '4H'), ('1d', '1D'))


def _format_price(price) -> str:
    return f"{price:,.2f}" if isinstance(price, (int, float)) else "N/A"


def _sma_block(sma_data: dict) -> str:
    """把四條均線與排列狀態排成 Telegram 用的區塊。"""
    if not sma_data:
        return "  暫無"

    lines = [f"{label}: {sma_data[key]:,.2f}" for key, label in SMA_LABELS
             if sma_data.get(key) is not None]

    values = [sma_data.get(key) for key, _ in SMA_LABELS]
    if all(v is not None for v in values):
        if all(a > b for a, b in zip(values, values[1:])):
            lines.append("排列: 多頭排列 (10&gt;60&gt;120&gt;720)")
        elif all(a < b for a, b in zip(values, values[1:])):
            lines.append("排列: 空頭排列 (10&lt;60&lt;120&lt;720)")
        else:
            lines.append("排列: 糾結")

    return "  " + "\n  ".join(lines) if lines else "  暫無"


def _kd_block(kd_data: dict) -> str:
    lines = []
    for key, label in KD_LABELS:
        entry = kd_data.get(key) or {}
        k = entry.get('k')
        d = entry.get('d')
        if k is not None and d is not None:
            lines.append(f"  {label}: K={k:.2f} D={d:.2f} [{entry.get('dir', '')}]")
    return "\n".join(lines) if lines else "  KD資料暫無"


def format_trading_signal(symbol: str, price: float, recommendation: str,
                          signal_strength: str, kd_data: dict,
                          sma_data: dict = None, trigger: str = None) -> str:
    """
    Format trading signal as Telegram message

    Args:
        symbol: Trading symbol (e.g., TXF1!)
        price: Current price
        recommendation: '做多', '做空', or '持有'
        signal_strength: '建議', '積極', '強烈', or '持續'
        kd_data: KD indicator data (1h/4h/1d)
        sma_data: SMA indicator data (sma10/60/120/720, 皆為 1H 週期)
        trigger: 觸發原因說明

    Returns:
        str: Formatted message
    """
    direction_emoji = DIRECTION_EMOJI.get(recommendation, "⚪")
    strength_prefix = STRENGTH_EMOJI.get(signal_strength, "📊")
    trigger_line = f"\n<b>觸發:</b> {trigger}" if trigger else ""

    message = f"""
{direction_emoji} <b>期貨訊號通知</b> {direction_emoji}

<b>標的:</b> {symbol}
<b>價格:</b> {_format_price(price)}
<b>建議:</b> {recommendation} {strength_prefix}
<b>強度:</b> {signal_strength}{trigger_line}

<b>SMA (1H):</b>
{_sma_block(sma_data)}

<b>KD指標:</b>
{_kd_block(kd_data)}

<i>此訊息由系統自動產生</i>
""".strip()

    return message


def format_trading_signal_no_kd(symbol: str, price: float, recommendation: str,
                                signal_strength: str, trigger: str = None) -> str:
    """
    Format trading signal message without KD details (for secondary bot)
    """
    direction_emoji = DIRECTION_EMOJI.get(recommendation, "⚪")
    strength_prefix = STRENGTH_EMOJI.get(signal_strength, "📊")
    trigger_line = f"\n<b>觸發:</b> {trigger}" if trigger else ""

    message = f"""
{direction_emoji} <b>期貨訊號通知</b> {direction_emoji}

<b>標的:</b> {symbol}
<b>價格:</b> {_format_price(price)}
<b>建議:</b> {recommendation} {strength_prefix}
<b>強度:</b> {signal_strength}{trigger_line}

<i>此訊息由系統自動產生</i>
""".strip()

    return message


def send_trading_notification(symbol: str, price: float, recommendation: str,
                              signal_strength: str, kd_data: dict,
                              secondary_message: str | None = None,
                              sma_data: dict = None, trigger: str = None,
                              send_secondary: bool = True) -> bool:
    """
    Send trading notification to Telegram

    - Primary bot receives full message with KD details
    - Secondary bot receives `secondary_message` if provided; otherwise it falls back
      to the simplified message without KD details

    Args:
        symbol: Trading symbol
        price: Current price
        recommendation: '做多', '做空', or '持有'
        signal_strength: '建議', '積極', '強烈', or '持續'
        kd_data: KD indicator data (1h/4h/1d)
        sma_data: SMA indicator data (sma10/60/120/720)
        trigger: 觸發原因說明

    Returns:
        bool: True if notification was sent successfully
    """
    message = format_trading_signal(
        symbol, price, recommendation, signal_strength, kd_data, sma_data, trigger
    )
    fallback_secondary_message = format_trading_signal_no_kd(
        symbol, price, recommendation, signal_strength, trigger
    )
    return send_telegram_message(
        message,
        secondary_message=secondary_message if secondary_message else fallback_secondary_message,
        send_secondary=send_secondary,
    )
