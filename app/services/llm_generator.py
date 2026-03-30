"""
LLM Generator Service

Generates trading recommendations using OpenRouter API with MiniMax M2.7 model.
"""

import requests
from app.config import Config


SYSTEM_PROMPT = """你是一個專業的期貨交易分析師。你的任務是根據KD指標數據，提供簡潔、專業的交易建議。

分析原則：
1. 只在有明確訊號時提供建議
2. 考慮不同時間週期的一致性
3. 提到預計持續時間
4. 使用繁體中文回覆
5. 回覆要簡潔有力，不超過200字
6. 不要逐一列出 K/D 數值明細，只需摘要判斷重點

回覆格式：
- 方向：做多/做空/觀望
- 理由：簡短說明
- 預期：可能的持續時間
"""


def generate_recommendation_message(symbol: str, price: float, 
                                   recommendation: str, signal_strength: str,
                                   kd_data: dict) -> str:
    """
    Generate trading recommendation message using LLM
    
    Args:
        symbol: Trading symbol
        price: Current price
        recommendation: '做多' or '做空'
        signal_strength: '建議', '積極', or '強烈'
        kd_data: KD indicator data
    
    Returns:
        str: Generated recommendation message
    """
    if not Config.OPENROUTER_API_KEY:
        # Fallback to simple template if no API key
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data)
    
    # Build user prompt with KD data
    kd_text = format_kd_for_prompt(kd_data)
    
    user_prompt = f"""期貨標的：{symbol}
價格：{price}
建議方向：{recommendation}
訊號強度：{signal_strength}

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
            'max_tokens': 300,
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
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            if content:
                return content.strip()
        
        print(f"[LLM] API error: {response.status_code} - {response.text[:200]}")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data)
        
    except Exception as e:
        print(f"[LLM] Exception: {str(e)}")
        return generate_simple_message(symbol, price, recommendation, signal_strength, kd_data)


def format_kd_for_prompt(kd_data: dict) -> str:
    """Format KD data for prompt"""
    lines = []
    timeframe_names = {
        '5m': '5分鐘',
        '30m': '30分鐘', 
        '60m': '60分鐘',
        '4h': '4小時',
        '1d': '1日'
    }
    
    for tf, data in kd_data.items():
        name = timeframe_names.get(tf, tf)
        k = data.get('k', 'N/A')
        d = data.get('d', 'N/A')
        direction = data.get('dir', 'N/A')
        lines.append(f"{name}: K={k}, D={d}, 方向={direction}")
    
    return '\n'.join(lines) if lines else '無數據'


def generate_simple_message(symbol: str, price: float,
                           recommendation: str, signal_strength: str,
                           kd_data: dict) -> str:
    """
    Generate simple template message (fallback when LLM unavailable)
    
    Args:
        symbol: Trading symbol
        price: Current price
        recommendation: '做多' or '做空'
        signal_strength: '建議', '積極', or '強烈'
        kd_data: KD indicator data
    
    Returns:
        str: Simple formatted message
    """
    direction_text = "做多" if recommendation == "做多" else "做空"
    emoji = "🟢" if recommendation == "做多" else "🔴"
    
    # Estimate duration based on strength
    durations = {
        "建議": "約1-2小時",
        "積極": "約4-8小時",
        "強烈": "約1天至數日"
    }
    duration = durations.get(signal_strength, "不確定")
    
    # Build short timeframe summary without exposing raw KD numbers
    bullish = []
    bearish = []
    for tf in ['30m', '60m', '4h']:
        if tf in kd_data:
            direction = kd_data[tf].get('dir')
            if direction == '多':
                bullish.append(tf)
            elif direction == '空':
                bearish.append(tf)

    if bullish and not bearish:
        trend_text = f"多方偏強（{' / '.join(bullish)}）"
    elif bearish and not bullish:
        trend_text = f"空方偏強（{' / '.join(bearish)}）"
    elif bullish or bearish:
        trend_text = "多空分歧，先保守看待"
    else:
        trend_text = "KD方向摘要暫缺"
    
    return f"""{emoji} <b>{symbol}</b> {direction_text}訊號

<b>強度:</b> {signal_strength}
<b>價格:</b> {price}
<b>判斷:</b> {trend_text}
<b>預期持續:</b> {duration}

<i>⚠️ 僅供參考，請自行判斷風險</i>"""
