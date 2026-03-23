"""
Telegram Bot Service

Sends trading recommendations to users via Telegram bot.
"""

import requests
from app.config import Config


def _send_telegram_message_via_bot(message: str, bot_token: str, user_id: str, label: str = 'Telegram') -> bool:
    """Send one Telegram message through a specific bot/user pair."""
    if not bot_token or bot_token == 'your-bot-token':
        print(f"[{label}] Bot token not configured. Message: {message[:100]}...")
        return False

    if not user_id:
        print(f"[{label}] User ID not configured.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': user_id,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()

        if result.get('ok'):
            print(f"[{label}] Message sent successfully")
            return True
        else:
            print(f"[{label}] Error: {result.get('description')}")
            return False
    except Exception as e:
        print(f"[{label}] Exception: {str(e)}")
        return False


def send_telegram_message(message: str, secondary_message: str | None = None) -> bool:
    """
    Send message to primary Telegram user and optionally to a second bot/user.

    - Primary bot always receives `message`
    - Secondary bot receives `secondary_message` if provided, otherwise falls back to `message`

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

    if Config.TELEGRAM_BOT_TOKEN_2 and Config.TELEGRAM_USER_ID_2:
        secondary_result = _send_telegram_message_via_bot(
            secondary_message if secondary_message else message,
            Config.TELEGRAM_BOT_TOKEN_2,
            Config.TELEGRAM_USER_ID_2,
            'Telegram-Secondary'
        )
        results.append(secondary_result)

    return any(results)


def format_trading_signal(symbol: str, price: float, recommendation: str, 
                          signal_strength: str, kd_data: dict) -> str:
    """
    Format trading signal as Telegram message
    
    Args:
        symbol: Trading symbol (e.g., TXF1!)
        price: Current price
        recommendation: '做多' or '做空'
        signal_strength: '建議', '積極', or '強烈'
        kd_data: KD indicator data
    
    Returns:
        str: Formatted message
    """
    direction_emoji = "🟢" if recommendation == "做多" else "🔴"
    strength_prefix = {
        "建議": "📊",
        "積極": "📈",
        "強烈": "🚨"
    }.get(signal_strength, "📊")
    
    # Build KD info
    kd_lines = []
    for timeframe in ['5m', '30m', '60m', '4h', '1d']:
        if timeframe in kd_data:
            k = kd_data[timeframe].get('k')
            d = kd_data[timeframe].get('d')
            direction = kd_data[timeframe].get('dir', '')
            if k is not None and d is not None:
                kd_lines.append(f"  {timeframe}: K={k:.2f} D={d:.2f} [{direction}]")
    
    kd_text = "\n".join(kd_lines) if kd_lines else "KD資料暫無"
    
    message = f"""
{direction_emoji} <b>期貨訊號通知</b> {direction_emoji}

<b>標的:</b> {symbol}
<b>價格:</b> {price}
<b>建議:</b> {recommendation} {strength_prefix}
<b>強度:</b> {signal_strength}

<b>KD指標:</b>
{kd_text}

<i>此訊息由系統自動產生</i>
""".strip()
    
    return message


def send_trading_notification(symbol: str, price: float, recommendation: str,
                              signal_strength: str, kd_data: dict,
                              secondary_message: str | None = None) -> bool:
    """
    Send trading notification to Telegram
    
    Args:
        symbol: Trading symbol
        price: Current price
        recommendation: '做多' or '做空'
        signal_strength: '建議', '積極', or '強烈'
        kd_data: KD indicator data
    
    Returns:
        bool: True if notification was sent successfully
    """
    message = format_trading_signal(
        symbol, price, recommendation, signal_strength, kd_data
    )
    return send_telegram_message(message, secondary_message=secondary_message)
