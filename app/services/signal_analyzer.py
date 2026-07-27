"""
Signal Analyzer Service

訊號來源：TradingView Pine 指標「KDJ_MTF_1H_4H_1D」，送出的是一個純數值陣列：

    [SMA10, SMA60, SMA120, SMA720, K1H, D1H, K4H, D4H, K1D, D1D, PRICE]

前四個 SMA 都是 1H 週期。陣列本身不帶商品代號、不帶方向，因此：

- 商品固定為 Config.DEFAULT_SYMBOL（台指期 TXF1!）
- 交叉方向一律靠「與資料庫上一筆比對」推導，不再有 signal:"UP"/"DOWN" 欄位
- SMA 不單獨產生買賣建議，只做強度加權與逆勢過濾
"""

from typing import Optional, Tuple

from app.config import Config
from app.models import get_previous_signal, has_recent_duplicate_notification, save_signal


# 陣列欄位順序（PRICE 為選填的第 11 個元素）
PAYLOAD_ORDER = (
    'sma10', 'sma60', 'sma120', 'sma720',
    'k_1h', 'd_1h', 'k_4h', 'd_4h', 'k_1d', 'd_1d',
    'price',
)
REQUIRED_LENGTH = 10

# 只剩單一訊號家族，保留欄位是為了沿用既有的「上一筆」與去重查詢
ALERT_GROUP = 'swing'

# 強度階梯，SMA 加權時在這條線上前後移動（'持續' 不參與加權）
STRENGTH_LADDER = ('無', '建議', '積極', '強烈')

TIMEFRAME_LABELS = {'1h': '1H', '4h': '4H', '1d': '1D'}


def _to_float(value) -> Optional[float]:
    """把 TradingView 傳來的值轉成 float，轉不動就當作沒有資料。"""
    if value is None or value == '':
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # 濾掉 NaN


def parse_payload(raw, symbol: str = None) -> dict:
    """
    把數值陣列轉成內部使用的 dict 結構。

    Args:
        raw: TradingView 送來的陣列（list/tuple）
        symbol: 覆寫商品代號，None 時使用 Config.DEFAULT_SYMBOL

    Returns:
        dict: {'symbol', 'price', 'sma', 'kd', 'values'}

    Raises:
        ValueError: 陣列長度不足或內容無法解析成數值
    """
    if not isinstance(raw, (list, tuple)):
        raise ValueError('payload 必須是數值陣列')
    if len(raw) < REQUIRED_LENGTH:
        raise ValueError(f'陣列長度不足：需要至少 {REQUIRED_LENGTH} 個元素，實際收到 {len(raw)} 個')

    values = [_to_float(v) for v in raw[:len(PAYLOAD_ORDER)]]
    fields = dict(zip(PAYLOAD_ORDER, values))

    kd = {}
    for tf in ('1h', '4h', '1d'):
        k = fields.get(f'k_{tf}')
        d = fields.get(f'd_{tf}')
        kd[tf] = {'k': k, 'd': d, 'dir': analyze_kd_indicator(k, d)}

    return {
        'symbol': symbol or Config.DEFAULT_SYMBOL,
        'price': fields.get('price'),
        'sma': {
            'sma10': fields.get('sma10'),
            'sma60': fields.get('sma60'),
            'sma120': fields.get('sma120'),
            'sma720': fields.get('sma720'),
        },
        'kd': kd,
        'values': list(raw),
    }


def analyze_kd_indicator(k: Optional[float], d: Optional[float]) -> str:
    """
    Analyze KD indicator direction

    Returns:
        str: '多' if K > D, '空' if K < D, '平' if K == D, '' if 資料缺漏
    """
    if k is None or d is None:
        return ''
    if k > d:
        return '多'
    if k < d:
        return '空'
    return '平'


def detect_crossover(prev_k: float, prev_d: float, curr_k: float, curr_d: float) -> Tuple[bool, bool]:
    """
    Detect K/D crossover

    Returns:
        Tuple: (is_cross_up, is_cross_down)
        - is_cross_up: K 由下向上穿越 D（空轉多）
        - is_cross_down: K 由上向下穿越 D（多轉空）
    """
    is_cross_up = (prev_k < prev_d) and (curr_k > curr_d)
    is_cross_down = (prev_k > prev_d) and (curr_k < curr_d)
    return is_cross_up, is_cross_down


def sma_alignment(sma: dict) -> str:
    """
    判斷 1H 均線排列。

    Returns:
        str: 'bull'（10>60>120>720）、'bear'（10<60<120<720）、'mixed'（其餘或資料缺漏）
    """
    ordered = [sma.get('sma10'), sma.get('sma60'), sma.get('sma120'), sma.get('sma720')]
    if any(v is None for v in ordered):
        return 'mixed'
    if all(a > b for a, b in zip(ordered, ordered[1:])):
        return 'bull'
    if all(a < b for a, b in zip(ordered, ordered[1:])):
        return 'bear'
    return 'mixed'


def _shift_strength(strength: str, step: int) -> str:
    """在強度階梯上移動；不在階梯上的強度（例如 '持續'）原樣返回。"""
    if strength not in STRENGTH_LADDER:
        return strength
    index = STRENGTH_LADDER.index(strength) + step
    index = max(0, min(len(STRENGTH_LADDER) - 1, index))
    return STRENGTH_LADDER[index]


def _kd_crosses(current_kd: dict, previous_data: Optional[dict]) -> dict:
    """
    跟資料庫上一筆比對，推導各週期的 K/D 交叉。

    Returns:
        dict: {'1h': (up, down), '4h': (...), '1d': (...)}
    """
    # 1H 沿用舊的 60m 欄位命名
    prev_columns = {'1h': ('k_60m', 'd_60m'), '4h': ('k_4h', 'd_4h'), '1d': ('k_1d', 'd_1d')}
    crosses = {tf: (False, False) for tf in prev_columns}

    if not previous_data:
        return crosses

    for tf, (k_col, d_col) in prev_columns.items():
        prev_k = previous_data.get(k_col)
        prev_d = previous_data.get(d_col)
        curr_k = current_kd.get(tf, {}).get('k')
        curr_d = current_kd.get(tf, {}).get('d')
        if all(v is not None for v in (prev_k, prev_d, curr_k, curr_d)):
            crosses[tf] = detect_crossover(prev_k, prev_d, curr_k, curr_d)

    return crosses


def analyze_signal(current_data: dict, previous_data: Optional[dict] = None) -> Tuple[str, str, str]:
    """
    分析 1H / 4H / 1D 的 KD 交叉，並用 1H 均線排列做強度加權。

    KD 判斷（做空對稱）：
      1. 1D 黃金交叉                      → 做多 / 強烈
      2. 4H 黃金交叉 + 1D 偏多            → 做多 / 強烈
      3. 4H 黃金交叉                      → 做多 / 積極
      4. 1H 黃金交叉 + 4H 偏多 + 1D 偏多  → 做多 / 積極
      5. 1H 黃金交叉 + 4H 偏多            → 做多 / 建議
      6. 1H 黃金交叉但 4H 偏空            → 逆勢，不建議進場
      7. 無交叉但 2 個以上週期同向        → 持有 / 持續

    SMA 加權：
      - 均線多頭排列（10>60>120>720）：做多升一級、做空降一級
      - 均線空頭排列（10<60<120<720）：做空升一級、做多降一級
      - 降到「無」就不推播（逆勢過濾）

    Args:
        current_data: parse_payload 產生的資料
        previous_data: 資料庫上一筆，用來偵測交叉

    Returns:
        Tuple: (recommendation, signal_strength, trigger)
        - recommendation: '做多' / '做空' / '持有' / '無'
        - signal_strength: '無' / '建議' / '積極' / '強烈' / '持續'
        - trigger: 觸發原因的文字說明
    """
    kd = current_data.get('kd', {}) or {}
    sma = current_data.get('sma', {}) or {}

    dirs = {tf: kd.get(tf, {}).get('dir', '') for tf in ('1h', '4h', '1d')}
    bullish = {tf: d == '多' for tf, d in dirs.items()}
    bearish = {tf: d == '空' for tf, d in dirs.items()}

    crosses = _kd_crosses(kd, previous_data)
    up = {tf: crosses[tf][0] for tf in crosses}
    down = {tf: crosses[tf][1] for tf in crosses}

    recommendation = '無'
    strength = '無'
    trigger = '無交叉'

    # ── 做多 ────────────────────────────────────────────────────────
    if up['1d']:
        recommendation, strength, trigger = '做多', '強烈', '1D 黃金交叉'
    elif up['4h']:
        recommendation = '做多'
        strength = '強烈' if bullish['1d'] else '積極'
        trigger = '4H 黃金交叉' + ('（1D 偏多）' if bullish['1d'] else '')
    elif up['1h']:
        trigger = '1H 黃金交叉'
        if bullish['4h'] and bullish['1d']:
            recommendation, strength = '做多', '積極'
            trigger += '（4H/1D 同步偏多）'
        elif bullish['4h']:
            recommendation, strength = '做多', '建議'
            trigger += '（4H 偏多）'
        else:
            trigger += '（4H 未同向，逆勢略過）'

    # ── 做空 ────────────────────────────────────────────────────────
    elif down['1d']:
        recommendation, strength, trigger = '做空', '強烈', '1D 死亡交叉'
    elif down['4h']:
        recommendation = '做空'
        strength = '強烈' if bearish['1d'] else '積極'
        trigger = '4H 死亡交叉' + ('（1D 偏空）' if bearish['1d'] else '')
    elif down['1h']:
        trigger = '1H 死亡交叉'
        if bearish['4h'] and bearish['1d']:
            recommendation, strength = '做空', '積極'
            trigger += '（4H/1D 同步偏空）'
        elif bearish['4h']:
            recommendation, strength = '做空', '建議'
            trigger += '（4H 偏空）'
        else:
            trigger += '（4H 未同向，逆勢略過）'

    # ── 無交叉：多週期同向視為持續持有 ──────────────────────────────
    else:
        bull_count = sum(bullish.values())
        bear_count = sum(bearish.values())
        if bull_count >= 2 and bear_count == 0:
            recommendation, strength = '持有', '持續'
            trigger = f"無交叉，{bull_count} 個週期偏多"
        elif bear_count >= 2 and bull_count == 0:
            recommendation, strength = '持有', '持續'
            trigger = f"無交叉，{bear_count} 個週期偏空"

    # ── SMA 加權 ────────────────────────────────────────────────────
    alignment = sma_alignment(sma)
    if recommendation in ('做多', '做空') and alignment != 'mixed':
        favourable = (recommendation == '做多' and alignment == 'bull') or \
                     (recommendation == '做空' and alignment == 'bear')
        strength = _shift_strength(strength, 1 if favourable else -1)
        trigger += '｜均線多頭排列' if alignment == 'bull' else '｜均線空頭排列'
        if not favourable:
            trigger += '（逆勢降級）'
        if strength == '無':
            recommendation = '無'

    return recommendation, strength, trigger


def should_notify(recommendation: str, signal_strength: str) -> bool:
    """
    Determine if notification should be sent

    Args:
        recommendation: '做多', '做空', '持有', or '無'
        signal_strength: '無', '建議', '積極', '強烈', '持續'

    Returns:
        bool: True if notification should be sent
    """
    return (
        recommendation in ('做多', '做空', '持有')
        and signal_strength in ('建議', '積極', '強烈', '持續')
    )


def process_signal(data: dict) -> dict:
    """
    Process incoming trading signal

    Args:
        data: parse_payload 產生的資料

    Returns:
        dict: Processing result with recommendation and signal strength
    """
    symbol = data.get('symbol')
    previous_data = get_previous_signal(symbol=symbol, alert_group=ALERT_GROUP)

    recommendation, signal_strength, trigger = analyze_signal(data, previous_data)

    row_id = save_signal(data, recommendation, signal_strength, alert_group=ALERT_GROUP)

    notify = should_notify(recommendation, signal_strength)
    duplicate_within_minute = False
    if notify:
        duplicate_within_minute = has_recent_duplicate_notification(
            symbol=symbol,
            alert_group=ALERT_GROUP,
            recommendation=recommendation,
            signal_strength=signal_strength,
            exclude_id=row_id,
            within_seconds=60,
        )
        if duplicate_within_minute:
            notify = False

    return {
        'row_id': row_id,
        'alert_group': ALERT_GROUP,
        'recommendation': recommendation,
        'signal_strength': signal_strength,
        'trigger': trigger,
        'should_notify': notify,
        'deduped': duplicate_within_minute,
    }
