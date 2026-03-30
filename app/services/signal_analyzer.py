"""
Signal Analyzer Service

Analyzes KD indicator data to generate trading recommendations.
Dual verification: TradingView signal field + historical data crossover detection.
"""

from typing import Tuple, Optional
from app.models import get_previous_signal, has_recent_duplicate_notification, save_signal


INTRADAY_ALERT_GROUP = 'intraday'
SWING_ALERT_GROUP = 'swing'
UNKNOWN_ALERT_GROUP = 'unknown'


def infer_alert_group(data: dict) -> str:
    """Infer which webhook family this payload belongs to."""
    kd = data.get('kd', {}) or {}
    keys = {str(k).lower() for k in kd.keys()}

    if {'5m', '30m'} & keys:
        return INTRADAY_ALERT_GROUP
    if {'4h', '1d'} & keys:
        return SWING_ALERT_GROUP
    timeframe = str(data.get('timeframe', '')).lower()
    if timeframe in {'5m', '30m', '60m'}:
        return INTRADAY_ALERT_GROUP
    if timeframe in {'1h', '4h', '1d'}:
        return SWING_ALERT_GROUP
    return UNKNOWN_ALERT_GROUP


def analyze_kd_indicator(k: float, d: float) -> str:
    """
    Analyze KD indicator direction
    
    Args:
        k: K value
        d: D value
    
    Returns:
        str: '多' if K > D, '空' if K < D, '平' if K == D
    """
    if k > d:
        return '多'
    elif k < d:
        return '空'
    return '平'


def detect_crossover(prev_k: float, prev_d: float, curr_k: float, curr_d: float) -> Tuple[bool, bool]:
    """
    Detect K/D crossover
    
    Args:
        prev_k, prev_d: Previous period values
        curr_k, curr_d: Current period values
    
    Returns:
        Tuple: (is_cross_up, is_cross_down)
        - is_cross_up: K crossed above D (空轉多)
        - is_cross_down: K crossed below D (多轉空)
    """
    is_cross_up = (prev_k < prev_d) and (curr_k > curr_d)
    is_cross_down = (prev_k > prev_d) and (curr_k < curr_d)
    return is_cross_up, is_cross_down


def analyze_signal(current_data: dict, previous_data: Optional[dict] = None) -> Tuple[str, str]:
    """
    Analyze trading signal with dual verification
    
    Logic:
    1. 30分鐘線偏多(K>D), 5分鐘線轉多(K由下穿越向上) → 建議做多
    2. 30分鐘線偏多 + 60分鐘線偏多, 5分鐘線轉多 → 積極建議做多
    3. 30分鐘線偏多 + 60分鐘線偏多 + 4小時線偏多, 5分鐘線轉多 → 強烈建議做多
    
    Same logic applies for short positions.
    
    Args:
        current_data: Current signal data with kd values
        previous_data: Previous signal data for crossover detection (optional)
    
    Returns:
        Tuple: (recommendation, signal_strength)
        - recommendation: '做多', '做空', or '無'
        - signal_strength: '無', '建議', '積極', '強烈'
    """
    kd = current_data.get('kd', {})
    
    # Extract current KD values
    curr_5m = kd.get('5m', {})
    curr_30m = kd.get('30m', {})
    curr_60m = kd.get('60m', {})
    curr_4h = kd.get('4h', {})
    curr_1d = kd.get('1d', {})
    
    curr_5m_k = curr_5m.get('k')
    curr_5m_d = curr_5m.get('d')
    curr_30m_k = curr_30m.get('k')
    curr_30m_d = curr_30m.get('d')
    curr_60m_k = curr_60m.get('k')
    curr_60m_d = curr_60m.get('d')
    curr_4h_k = curr_4h.get('k')
    curr_4h_d = curr_4h.get('d')
    
    # Determine current directions
    is_5m_bullish = curr_5m_k > curr_5m_d if curr_5m_k and curr_5m_d else False
    is_5m_bearish = curr_5m_k < curr_5m_d if curr_5m_k and curr_5m_d else False
    is_30m_bullish = curr_30m_k > curr_30m_d if curr_30m_k and curr_30m_d else False
    is_60m_bullish = curr_60m_k > curr_60m_d if curr_60m_k and curr_60m_d else False
    is_4h_bullish = curr_4h_k > curr_4h_d if curr_4h_k and curr_4h_d else False
    is_30m_bearish = curr_30m_k < curr_30m_d if curr_30m_k and curr_30m_d else False
    is_60m_bearish = curr_60m_k < curr_60m_d if curr_60m_k and curr_60m_d else False
    is_4h_bearish = curr_4h_k < curr_4h_d if curr_4h_k and curr_4h_d else False
    
    # Crossover detection using historical data
    is_5m_cross_up = False
    is_5m_cross_down = False
    is_30m_cross_up = False
    is_30m_cross_down = False
    is_60m_cross_up = False
    is_60m_cross_down = False

    if previous_data:
        prev_5m_k = previous_data.get('k_5m')
        prev_5m_d = previous_data.get('d_5m')
        prev_30m_k = previous_data.get('k_30m')
        prev_30m_d = previous_data.get('d_30m')
        prev_60m_k = previous_data.get('k_60m')
        prev_60m_d = previous_data.get('d_60m')

        if all(v is not None for v in [prev_5m_k, prev_5m_d, curr_5m_k, curr_5m_d]):
            is_5m_cross_up, is_5m_cross_down = detect_crossover(
                prev_5m_k, prev_5m_d, curr_5m_k, curr_5m_d
            )
        if all(v is not None for v in [prev_30m_k, prev_30m_d, curr_30m_k, curr_30m_d]):
            is_30m_cross_up, is_30m_cross_down = detect_crossover(
                prev_30m_k, prev_30m_d, curr_30m_k, curr_30m_d
            )
        if all(v is not None for v in [prev_60m_k, prev_60m_d, curr_60m_k, curr_60m_d]):
            is_60m_cross_up, is_60m_cross_down = detect_crossover(
                prev_60m_k, prev_60m_d, curr_60m_k, curr_60m_d
            )
    else:
        # Fallback: Use TradingView signal field if no historical data
        signal = current_data.get('signal', '').upper()
        if signal == 'UP':
            is_5m_cross_up = True
        elif signal == 'DOWN':
            is_5m_cross_down = True
    
    # Analysis logic
    recommendation = '無'
    signal_strength = '無'
    
    # Bullish analysis
    if is_30m_bullish and is_5m_cross_up:
        if is_60m_bullish and is_4h_bullish:
            recommendation = '做多'
            signal_strength = '強烈'
        elif is_60m_bullish:
            recommendation = '做多'
            signal_strength = '積極'
        else:
            recommendation = '做多'
            signal_strength = '建議'

    # 30m 剛轉多，且 5m 已偏多
    elif is_30m_cross_up and is_5m_bullish:
        recommendation = '做多'
        signal_strength = '建議'

    # 60m 剛轉多，且 5m + 30m 已偏多
    elif is_60m_cross_up and is_5m_bullish and is_30m_bullish:
        recommendation = '做多'
        signal_strength = '積極'

    # Bearish analysis
    elif is_30m_bearish and is_5m_cross_down:
        if is_60m_bearish and is_4h_bearish:
            recommendation = '做空'
            signal_strength = '強烈'
        elif is_60m_bearish:
            recommendation = '做空'
            signal_strength = '積極'
        else:
            recommendation = '做空'
            signal_strength = '建議'

    # 30m 剛轉空，且 5m 已偏空
    elif is_30m_cross_down and is_5m_bearish:
        recommendation = '做空'
        signal_strength = '建議'

    # 60m 剛轉空，且 5m + 30m 已偏空
    elif is_60m_cross_down and is_5m_bearish and is_30m_bearish:
        recommendation = '做空'
        signal_strength = '積極'

    return recommendation, signal_strength


def should_notify(recommendation: str, signal_strength: str) -> bool:
    """
    Determine if notification should be sent
    
    Args:
        recommendation: '做多', '做空', or '無'
        signal_strength: '無', '建議', '積極', '強烈'
    
    Returns:
        bool: True if notification should be sent
    """
    if recommendation in ('做多', '做空') and signal_strength in ('建議', '積極', '強烈'):
        return True
    return False


def process_signal(data: dict, alert_group: str | None = None) -> dict:
    """
    Process incoming trading signal
    
    Args:
        data: TradingView webhook data
    
    Returns:
        dict: Processing result with recommendation and signal strength
    """
    # Get previous signal for crossover detection
    symbol = data.get('symbol')
    alert_group = alert_group or infer_alert_group(data)
    previous_data = get_previous_signal(symbol=symbol, alert_group=alert_group)
    
    # Analyze signal
    recommendation, signal_strength = analyze_signal(data, previous_data)
    
    # Save to database
    row_id = save_signal(data, recommendation, signal_strength, alert_group=alert_group)
    
    # Get previous data again after save for potential re-analysis
    if previous_data is None:
        previous_data = get_previous_signal(symbol=symbol, before_id=row_id, alert_group=alert_group)
        if previous_data:
            # Re-analyze with full history
            recommendation, signal_strength = analyze_signal(data, previous_data)
            # Update the record
            from app.models import get_db
            conn = get_db()
            conn.execute('''
                UPDATE trading_signals 
                SET recommendation = ?, signal_strength = ?
                WHERE id = ?
            ''', (recommendation, signal_strength, row_id))
            conn.commit()
            conn.close()
    
    # Check if notification should be sent
    notify = should_notify(recommendation, signal_strength)
    duplicate_within_minute = False
    if notify:
        duplicate_within_minute = has_recent_duplicate_notification(
            symbol=symbol,
            alert_group=alert_group,
            recommendation=recommendation,
            signal_strength=signal_strength,
            exclude_id=row_id,
            within_seconds=60,
        )
        if duplicate_within_minute:
            notify = False
    
    return {
        'row_id': row_id,
        'alert_group': alert_group,
        'recommendation': recommendation,
        'signal_strength': signal_strength,
        'should_notify': notify,
        'deduped': duplicate_within_minute
    }
