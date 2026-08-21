"""
LLM Generator Service

Generates trading recommendations using OpenRouter API with MiniMax M2.7 model.
"""

import re
import requests
from app.config import Config


SYSTEM_PROMPT = """你是一個專業的期貨交易分析師。你的任務是根據KD指標與均線數據，提供簡潔、專業的交易建議。

分析原則：
1. 只在有明確訊號時提供建議
2. 考慮 1H / 4H / 1D 三個時間週期的一致性
3. 均線（SMA10/60/120/720，皆為1H週期）的排列代表中長期趨勢，要納入判斷
4. 提到預計持續時間
5. 使用繁體中文回覆
6. 回覆要簡潔有力，不超過200字
7. 不要逐一列出 K/D 數值明細，只需摘要判斷重點

回覆格式（不使用任何 Markdown 符號，直接文字）：
方向：做多/做空/觀望
理由：簡短說明
預期：可能的持續時間
"""


def generate_recommendation_message(symbol: str, price: float,
                                   recommendation: str, signal_strength: str,
                                   kd_data: dict, sma_data: dict = None,
                                   trigger: str = None) -> str:
    """
    Generate trading recommendation message using LLM

    Args:
        symbol: Trading symbol
        price: Current price
        recommendation: '做多', '做空', or '持有'
        signal_strength: '建議', '積極', '強烈', or '持續'
        kd_data: KD indicator data (1h/4h/1d)
        sma_data: SMA indicator data (sma10/60/120/720, 皆為 1H 週期)
        trigger: 觸發原因說明

    Returns:
        str: Generated recommendation message
    """
    # Determine which provider to use
    provider = getattr(Config, 'LLM_PROVIDER', 'openrouter').lower()
    
    if provider == 'agnes':
        return generate_agnes_message(symbol, price, recommendation, signal_strength, kd_data, sma_data, trigger)
    else:
        return generate_openrouter_message(symbol, price, recommendation, signal_strength, kd_data, sma_data, trigger)


def generate_openrouter_message(symbol: str, price: float,
                                recommendation: str, signal_strength: str,
                                kd_data: dict, sma_data: dict = None,
                                trigger: str = None) -> str:
    """Generate message using OpenRouter API"""
    if not Config.OPENROUTER_API_KEY:
        # Fallback to simple template if no API key
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)

    # Build user prompt with KD data
    kd_text = format_kd_for_prompt(kd_data)
    sma_text = format_sma_for_prompt(sma_data) if sma_data else "無"

    user_prompt = f"""期貨標的：{symbol}
價格：{price if price is not None else '未提供'}
建議方向：{recommendation}
訊號強度：{signal_strength}
觸發原因：{trigger or '未提供'}

SMA指標數據（1H週期）：
{sma_text}

KD指標數據：
{kd_text}

請提供專業的交易建議。"""

    try:
        headers = {
            'Authorization': f'Bearer {Config.OPENROUTER_API_KEY}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://trading.thetainformation.com',
            'X-Title': 'Trading Signal Bot'
        }

        payload = {
            'model': Config.OPENROUTER_MODEL,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt}
            ],
            'max_tokens': 200000,
            'temperature': 0.7
        }

        response = requests.post(
            Config.OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:
            result = response.json()
            choice = result.get('choices', [{}])[0]
            content = choice.get('message', {}).get('content', '')

            # Detect if response was truncated due to max_tokens limit
            finish_reason = choice.get('finish_reason', '')
            if finish_reason == 'length':
                print(f"[LLM] Response truncated (max_tokens={payload.get('max_tokens')}), falling back to template")
                return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)

            if content:
                # Strip common Markdown symbols before sending to Telegram (which uses HTML parse_mode)
                cleaned = content.strip()
                cleaned = re.sub(r'#{1,6}\s*', '', cleaned)   # Remove # headers
                cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)  # Remove bold
                cleaned = re.sub(r'\*(.+?)\*', r'\1', cleaned)    # Remove italic
                cleaned = re.sub(r'~~(.+?)~~', r'\1', cleaned)    # Remove strikethrough
                cleaned = re.sub(r'`(.+?)`', r'\1', cleaned)      # Remove inline code
                cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)   # Remove code blocks
                return cleaned

        print(f"[LLM] API error: {response.status_code} - {response.text[:200]}")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)

    except Exception as e:
        print(f"[LLM] Exception: {str(e)}")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)


def generate_agnes_message(symbol: str, price: float,
                           recommendation: str, signal_strength: str,
                           kd_data: dict, sma_data: dict = None,
                           trigger: str = None) -> str:
    """Generate message using Agnes AI API"""
    if not Config.AGNES_API_KEY:
        print("[LLM Agnes] API key not set, falling back to template")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)

    # Build user prompt with KD data
    kd_text = format_kd_for_prompt(kd_data)
    sma_text = format_sma_for_prompt(sma_data) if sma_data else "無"

    user_prompt = f"""期貨標的：{symbol}
價格：{price if price is not None else '未提供'}
建議方向：{recommendation}
訊號強度：{signal_strength}
觸發原因：{trigger or '未提供'}

SMA指標數據（1H週期）：
{sma_text}

KD指標數據：
{kd_text}

請提供專業的交易建議。"""

    try:
        headers = {
            'Authorization': f'Bearer {Config.AGNES_API_KEY}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': Config.AGNES_MODEL,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt}
            ],
            'max_tokens': 200,
            'temperature': 0.7
        }

        response = requests.post(
            Config.AGNES_API_URL,
            headers=headers,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:
            result = response.json()
            choice = result.get('choices', [{}])[0]
            content = choice.get('message', {}).get('content', '')

            if content:
                # Strip common Markdown symbols
                cleaned = content.strip()
                cleaned = re.sub(r'#{1,6}\s*', '', cleaned)
                cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)
                cleaned = re.sub(r'\*(.+?)\*', r'\1', cleaned)
                cleaned = re.sub(r'~~(.+?)~~', r'\1', cleaned)
                cleaned = re.sub(r'`(.+?)`', r'\1', cleaned)
                cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)
                return cleaned

        print(f"[LLM Agnes] API error: {response.status_code} - {response.text[:200]}")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)

    except Exception as e:
        print(f"[LLM Agnes] Exception: {str(e)}")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data, sma_data)


SMA_KEYS = (('sma10', 'SMA10'), ('sma60', 'SMA60'), ('sma120', 'SMA120'), ('sma720', 'SMA720'))
TIMEFRAME_NAMES = {'1h': '1小時', '4h': '4小時', '1d': '1日'}


def describe_sma_alignment(sma_data: dict) -> str:
    """回傳均線排列的中文描述，資料不齊時回 '資料不足'。"""
    values = [sma_data.get(key) for key, _ in SMA_KEYS]
    if any(v is None for v in values):
        return '資料不足'
    if all(a > b for a, b in zip(values, values[1:])):
        return '多頭排列（10>60>120>720）'
    if all(a < b for a, b in zip(values, values[1:])):
        return '空頭排列（10<60<120<720）'
    return '糾結（無明確排列）'


def format_sma_for_prompt(sma_data: dict) -> str:
    """Format SMA data for prompt"""
    if not sma_data:
        return "無"
    lines = [f"{label}: {sma_data[key]:.2f}" for key, label in SMA_KEYS
             if sma_data.get(key) is not None]
    if not lines:
        return '無'
    lines.append(f"均線排列: {describe_sma_alignment(sma_data)}")
    return '\n'.join(lines)


def format_kd_for_prompt(kd_data: dict) -> str:
    """Format KD data for prompt"""
    lines = []
    for tf in ('1h', '4h', '1d'):
        data = kd_data.get(tf)
        if not data:
            continue
        name = TIMEFRAME_NAMES.get(tf, tf)
        k = data.get('k', 'N/A')
        d = data.get('d', 'N/A')
        direction = data.get('dir') or 'N/A'
        lines.append(f"{name}: K={k}, D={d}, 方向={direction}")

    return '\n'.join(lines) if lines else '無數據'


def generate_simple_message(symbol: str, price: float,
                           recommendation: str, signal_strength: str,
                           kd_data: dict, sma_data: dict = None) -> str:
    """
    Generate simple template message (fallback when LLM unavailable)

    Args:
        symbol: Trading symbol
        price: Current price
        recommendation: '做多', '做空', or '持有'
        signal_strength: '建議', '積極', '強烈', or '持續'
        kd_data: KD indicator data (1h/4h/1d)
        sma_data: SMA indicator data (sma10/60/120/720)

    Returns:
        str: Simple formatted message
    """
    emoji_map = {"做多": "🟢", "做空": "🔴", "持有": "🟡"}
    direction_map = {"做多": "做多", "做空": "做空", "持有": "觀望（持有）"}
    emoji = emoji_map.get(recommendation, "⚪")
    direction_text = direction_map.get(recommendation, recommendation)

    # Estimate duration based on strength
    durations = {
        "建議": "約4-8小時",
        "積極": "約1天至數日",
        "強烈": "約數日至數週",
        "持續": "趨勢持續中"
    }
    duration = durations.get(signal_strength, "不確定")

    # Build short timeframe summary without exposing raw KD numbers
    bullish = []
    bearish = []
    for tf, label in (('1h', '1H'), ('4h', '4H'), ('1d', '1D')):
        direction = (kd_data.get(tf) or {}).get('dir')
        if direction == '多':
            bullish.append(label)
        elif direction == '空':
            bearish.append(label)

    if bullish and not bearish:
        trend_text = f"多方偏強（{' / '.join(bullish)}）"
    elif bearish and not bullish:
        trend_text = f"空方偏強（{' / '.join(bearish)}）"
    elif bullish or bearish:
        trend_text = "多空分歧，先保守看待"
    else:
        trend_text = "KD方向摘要暫缺"

    # SMA summary
    sma_summary = ""
    if sma_data:
        alignment = describe_sma_alignment(sma_data)
        if alignment != '資料不足':
            sma_summary = f" | 均線{alignment}"

    price_text = f"{price:,.2f}" if isinstance(price, (int, float)) else "N/A"

    return f"""{emoji} <b>{symbol}</b> {direction_text}訊號

<b>強度:</b> {signal_strength}
<b>價格:</b> {price_text}{sma_summary}
<b>判斷:</b> {trend_text}
<b>預期:</b> {duration}

<i>⚠️ 僅供參考，請自行判斷風險</i>"""