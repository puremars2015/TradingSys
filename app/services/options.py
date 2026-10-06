"""
Options Service — 台指選擇權（TXO）未平倉資料，三種來源都是期交所 CSV：

1. 外資選擇權留倉：「三大法人 - 選擇權買賣權分計」callsAndPutsDateDown
   欄位：日期,商品名稱,買賣權別,身份別,買方交易口數,…,買方未平倉口數,買方未平倉契約金額(千元),
        賣方未平倉口數,賣方未平倉契約金額(千元),…
2. 全市場 P/C Ratio：「臺指選擇權 Put/Call 比」pcRatioDown
   欄位：日期,賣權成交量,買權成交量,買賣權成交量比率%,賣權未平倉量,買權未平倉量,買賣權未平倉量比率%
3. 各履約價未平倉：「選擇權每日交易行情」optDataDown
   欄位：交易日期,契約,到期月份(週別),履約價,買賣權,…,結算價,未沖銷契約數,…,交易時段,…
   只取一般交易時段（盤後時段沒有未沖銷契約數）。

手動補資料：
    python -m app.services.options --backfill 365
"""

import argparse
from datetime import date, datetime, timedelta

from app.models import (
    get_latest_foreign_options_date, get_latest_option_strike_date, get_latest_pc_ratio_date,
    upsert_foreign_options, upsert_option_strikes, upsert_pc_ratio,
)
from app.services.taifex_client import column, post_csv, read_rows, sync_by_chunks, to_int, to_number

INSTITUTIONAL_URL = 'https://www.taifex.com.tw/cht/3/callsAndPutsDateDown'
PC_RATIO_URL = 'https://www.taifex.com.tw/cht/3/pcRatioDown'
DAILY_URL = 'https://www.taifex.com.tw/cht/3/optDataDown'

COMMODITY = 'TXO'
DEFAULT_BACKFILL_DAYS = 365
# 每日行情一天上千筆，只補最近幾天就好（履約價分布只看近期）
STRIKE_BACKFILL_DAYS = 7


def _iso(text: str):
    try:
        return datetime.strptime(text.strip(), '%Y/%m/%d').date().isoformat()
    except (ValueError, AttributeError):
        return None


def _start(latest, today: date, backfill_days: int) -> date:
    return date.fromisoformat(latest) + timedelta(days=1) if latest else today - timedelta(days=backfill_days)


# ── 1. 外資選擇權留倉 ─────────────────────────────────────────────

def parse_institutional(text: str, commodity: str = COMMODITY) -> list:
    """只留外資那兩列（買權、賣權），每天合成一筆。"""
    records = read_rows(text, ('日期', '身份別'))
    if not records:
        return []
    keys = list(records[0].keys())
    side_col = column(keys, '買賣權別') or next((k for k in keys if '權別' in k), None)
    cols = {
        'buy_oi': column(keys, '買方未平倉口數'),
        'buy_amount': column(keys, '買方未平倉契約金額'),
        'sell_oi': column(keys, '賣方未平倉口數'),
        'sell_amount': column(keys, '賣方未平倉契約金額'),
    }
    if not side_col or not all(cols.values()):
        print(f"[ForeignOptions] Unexpected columns: {keys}", flush=True)
        return []

    by_date = {}
    for record in records:
        if '外資' not in record.get('身份別', ''):
            continue
        trade_date = _iso(record.get('日期', ''))
        side = record.get(side_col, '')
        prefix = 'call' if '買權' in side else 'put' if '賣權' in side else None
        if not trade_date or not prefix:
            continue
        row = by_date.setdefault(trade_date, {'trade_date': trade_date, 'commodity': commodity})
        for key, col in cols.items():
            row[f'{prefix}_{key}'] = to_int(record.get(col))

    return [r for r in by_date.values() if r.get('call_buy_oi') is not None and r.get('put_buy_oi') is not None]


def fetch_institutional(start: date, end: date) -> list:
    text = post_csv(INSTITUTIONAL_URL, {
        'queryStartDate': start.strftime('%Y/%m/%d'),
        'queryEndDate': end.strftime('%Y/%m/%d'),
        'commodityId': COMMODITY,
    })
    return parse_institutional(text)


def sync_foreign_options(today: date = None, start: date = None,
                         backfill_days: int = DEFAULT_BACKFILL_DAYS) -> int:
    today = today or date.today()
    start = start or _start(get_latest_foreign_options_date(COMMODITY), today, backfill_days)
    return sync_by_chunks(fetch_institutional, upsert_foreign_options, start, today, 30, 'ForeignOptions')


# ── 2. 全市場 P/C Ratio ──────────────────────────────────────────

def parse_pc_ratio(text: str) -> list:
    records = read_rows(text, ('日期',))
    rows = []
    for record in records:
        keys = list(record.keys())
        trade_date = _iso(record.get('日期', ''))
        if not trade_date:
            continue
        row = {
            'trade_date': trade_date,
            'put_volume': to_int(record.get(column(keys, '賣權成交量'))),
            'call_volume': to_int(record.get(column(keys, '買權成交量'))),
            'volume_ratio': to_number(record.get(column(keys, '買賣權成交量比率'))),
            'put_oi': to_int(record.get(column(keys, '賣權未平倉量'))),
            'call_oi': to_int(record.get(column(keys, '買權未平倉量'))),
            'oi_ratio': to_number(record.get(column(keys, '買賣權未平倉量比率'))),
        }
        if row['oi_ratio'] is None and row['put_oi'] and row['call_oi']:
            row['oi_ratio'] = round(row['put_oi'] / row['call_oi'] * 100, 2)
        if row['oi_ratio'] is not None:
            rows.append(row)
    return rows


def fetch_pc_ratio(start: date, end: date) -> list:
    text = post_csv(PC_RATIO_URL, {
        'queryStartDate': start.strftime('%Y/%m/%d'),
        'queryEndDate': end.strftime('%Y/%m/%d'),
    })
    return parse_pc_ratio(text)


def sync_pc_ratio(today: date = None, start: date = None,
                  backfill_days: int = DEFAULT_BACKFILL_DAYS) -> int:
    today = today or date.today()
    start = start or _start(get_latest_pc_ratio_date(), today, backfill_days)
    return sync_by_chunks(fetch_pc_ratio, upsert_pc_ratio, start, today, 30, 'PCRatio')


# ── 3. 各履約價未平倉 ─────────────────────────────────────────────

def parse_daily_options(text: str, commodity: str = COMMODITY) -> list:
    """彙整成每個 (交易日, 到期, 履約價) 一筆，Call/Put 的未平倉與結算價放同一列。"""
    records = read_rows(text, ('交易日期', '履約價'))
    if not records:
        return []
    keys = list(records[0].keys())
    expiry_col = column(keys, '到期月份')
    side_col = column(keys, '買賣權')
    oi_col = column(keys, '未沖銷契約數')
    settle_col = column(keys, '結算價')
    session_col = column(keys, '交易時段')
    if not (expiry_col and side_col and oi_col):
        print(f"[OptionStrikes] Unexpected columns: {keys}", flush=True)
        return []

    merged = {}
    for record in records:
        if record.get('契約', commodity) != commodity:
            continue
        if session_col and '盤後' in record.get(session_col, ''):
            continue
        trade_date = _iso(record.get('交易日期', ''))
        strike = to_number(record.get('履約價'))
        expiry = record.get(expiry_col, '').replace(' ', '')
        side = record.get(side_col, '')
        prefix = 'call' if '買權' in side or side.lower() == 'call' else \
            'put' if '賣權' in side or side.lower() == 'put' else None
        if not (trade_date and strike is not None and expiry and prefix):
            continue
        row = merged.setdefault((trade_date, expiry, strike), {
            'trade_date': trade_date, 'expiry': expiry, 'strike': strike,
            'call_oi': None, 'put_oi': None, 'call_settle': None, 'put_settle': None,
        })
        row[f'{prefix}_oi'] = to_int(record.get(oi_col))
        row[f'{prefix}_settle'] = to_number(record.get(settle_col)) if settle_col else None

    return list(merged.values())


def fetch_daily_options(start: date, end: date) -> list:
    text = post_csv(DAILY_URL, {
        'down_type': '1',
        'commodity_id': COMMODITY,
        'commodity_id2': '',
        'queryStartDate': start.strftime('%Y/%m/%d'),
        'queryEndDate': end.strftime('%Y/%m/%d'),
    })
    return parse_daily_options(text)


def sync_option_strikes(today: date = None, start: date = None,
                        backfill_days: int = STRIKE_BACKFILL_DAYS) -> int:
    today = today or date.today()
    start = start or _start(get_latest_option_strike_date(), today, backfill_days)
    return sync_by_chunks(fetch_daily_options, upsert_option_strikes, start, today, 7, 'OptionStrikes')


# ── 到期代號 ─────────────────────────────────────────────────────

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def expiry_date(code: str):
    """
    推算到期日：'202610' 月選 = 第三個週三；'202610W2' = 第二個週三；'202610F1' = 第一個週五。
    認不得的代號回 None。
    """
    try:
        year, month = int(code[:4]), int(code[4:6])
        suffix = code[6:]
        if not suffix:
            return _nth_weekday(year, month, 2, 3)
        n = int(suffix[1:])
        if suffix[0] == 'W':
            return _nth_weekday(year, month, 2, n)
        if suffix[0] == 'F':
            return _nth_weekday(year, month, 4, n)
    except (ValueError, IndexError):
        pass
    return None


def expiry_label(code: str) -> str:
    expires = expiry_date(code)
    kind = '月選' if len(code) == 6 else ('週三週選' if code[6:7] == 'W' else '週五週選' if code[6:7] == 'F' else '')
    return f"{code}（{kind}，{expires.strftime('%m/%d')} 到期）" if expires else code


def sync_all(today: date = None, backfill: int = None) -> None:
    today = today or date.today()
    start = today - timedelta(days=backfill) if backfill else None
    sync_foreign_options(today=today, start=start)
    sync_pc_ratio(today=today, start=start)
    sync_option_strikes(today=today, start=today - timedelta(days=min(backfill, 30)) if backfill else None)


def main():
    parser = argparse.ArgumentParser(description='同步期交所台指選擇權未平倉資料')
    parser.add_argument('--backfill', type=int, default=None,
                        help='強制從 N 天前重抓到今天（履約價分布最多補 30 天）；不給就只補最後一天之後')
    args = parser.parse_args()

    from app.models import init_db
    init_db()
    sync_all(backfill=args.backfill)


if __name__ == '__main__':
    main()
