"""
TAIEX Service

每天從證交所「市場成交資訊」(FMTQIK) 抓加權指數收盤與當日成交量，存進 SQLite
給 /taiex 畫圖。FMTQIK 一次回傳整個月，JSON 格式：

    {"stat": "OK",
     "fields": ["日期","成交股數","成交金額","成交筆數","發行量加權股價指數","漲跌點數"],
     "data": [["115/10/01","7,123,456,789","412,345,678,901","2,345,678","22,345.67","-123.45"], ...]}

日期是民國年。查無資料時 stat 會是「很抱歉，沒有符合條件的資料!」之類的訊息。

手動補歷史資料：
    python -m app.services.taiex --backfill 365
"""

import argparse
import time
from datetime import date, timedelta
from typing import Optional

import requests

from app.models import get_latest_taiex_date, upsert_taiex

TWSE_FMTQIK_URL = 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK'
DEFAULT_BACKFILL_DAYS = 365
# 證交所對連續請求很敏感（太快會被暫時封鎖 IP），逐月補資料時每次間隔幾秒
REQUEST_INTERVAL_SECONDS = 3

FIELD_MAP = {
    '成交股數': 'volume_shares',
    '成交金額': 'turnover',
    '成交筆數': 'transactions',
    '發行量加權股價指數': 'close',
    '漲跌點數': 'change',
}
INT_FIELDS = {'volume_shares', 'turnover', 'transactions'}


def _to_number(value) -> Optional[float]:
    text = str(value or '').replace(',', '').replace('+', '').strip()
    if not text or text in ('-', '--'):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _roc_to_iso(text: str) -> Optional[str]:
    """'115/10/01' → '2026-10-01'"""
    try:
        y, m, d = (int(p) for p in text.strip().split('/'))
        return date(y + 1911 if y < 1911 else y, m, d).isoformat()
    except (ValueError, AttributeError):
        return None


def parse_fmtqik(payload: dict) -> list:
    """
    解析 FMTQIK JSON。

    Returns:
        list[dict]: [{'trade_date', 'close', 'change', 'turnover', 'volume_shares', 'transactions'}]
    """
    if not isinstance(payload, dict) or payload.get('stat') != 'OK':
        stat = payload.get('stat') if isinstance(payload, dict) else payload
        if stat:
            print(f"[TAIEX] No data: {str(stat)[:80]}", flush=True)
        return []

    fields = payload.get('fields') or []
    rows = []
    for raw in payload.get('data') or []:
        record = dict(zip(fields, raw))
        trade_date = _roc_to_iso(record.get('日期', ''))
        if not trade_date:
            continue
        row = {'trade_date': trade_date}
        for field, key in FIELD_MAP.items():
            value = _to_number(record.get(field))
            row[key] = int(value) if key in INT_FIELDS and value is not None else value
        if row['close'] is None:
            continue
        rows.append(row)
    return rows


def fetch_month(month: date) -> list:
    """抓某個月份（取該月任一天）的每日資料。"""
    response = requests.get(
        TWSE_FMTQIK_URL,
        params={'date': month.strftime('%Y%m01'), 'response': 'json'},
        headers={'User-Agent': 'Mozilla/5.0 (TradingSys TAIEX sync)'},
        timeout=30,
    )
    response.raise_for_status()
    return parse_fmtqik(response.json())


def _months(start: date, end: date) -> list:
    months = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return months


def sync_taiex(backfill_days: int = DEFAULT_BACKFILL_DAYS, today: date = None,
               start: date = None) -> int:
    """
    從資料庫最後一天所在的月份抓到這個月；資料庫是空的就往回補 backfill_days 天。
    指定 start 時強制從那天所在的月份重抓（已存在的日期會覆寫）。

    Returns:
        int: 寫入（新增或更新）的筆數
    """
    today = today or date.today()
    if start is None:
        latest = get_latest_taiex_date()
        start = date.fromisoformat(latest) if latest else today - timedelta(days=backfill_days)

    saved = 0
    months = _months(start, today)
    for i, month in enumerate(months):
        rows = [r for r in fetch_month(month) if r['trade_date'] >= start.isoformat()]
        saved += upsert_taiex(rows)
        if i < len(months) - 1:
            time.sleep(REQUEST_INTERVAL_SECONDS)

    print(f"[TAIEX] Synced: {saved} rows", flush=True)
    return saved


def main():
    parser = argparse.ArgumentParser(description='同步證交所加權指數與成交量')
    parser.add_argument('--backfill', type=int, default=None,
                        help='強制從 N 天前重抓到今天；不給就只補資料庫最後一天之後的部分')
    args = parser.parse_args()

    from app.models import init_db
    init_db()
    start = date.today() - timedelta(days=args.backfill) if args.backfill else None
    sync_taiex(start=start)


if __name__ == '__main__':
    main()
