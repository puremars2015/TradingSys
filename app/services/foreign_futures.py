"""
Foreign Futures Service

每天從期交所抓「三大法人 - 區分各期貨契約」的 CSV，取出外資（外資及陸資）
的期貨未平倉（留倉）多單、空單、淨額，存進 SQLite 給 /foreign-futures 畫圖。

資料來源：https://www.taifex.com.tw/cht/3/futContractsDate（下載端點 futContractsDateDown）
CSV 為 Big5 編碼，欄位：

    日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),
    多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),
    空方未平倉口數,空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)

手動補歷史資料：
    python -m app.services.foreign_futures --backfill 365
"""

import argparse
import csv
import io
import time
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from app.config import Config
from app.models import get_latest_foreign_futures_date, upsert_foreign_futures

TAIFEX_DOWNLOAD_URL = 'https://www.taifex.com.tw/cht/3/futContractsDateDown'

# 期交所單次查詢區間有上限，補資料時切成小段逐段抓
CHUNK_DAYS = 30
DEFAULT_BACKFILL_DAYS = 365

# CSV 欄位名稱 → 內部欄位（未平倉口數與契約金額）
OI_COLUMNS = {
    '多方未平倉口數': 'long_oi',
    '多方未平倉契約金額(千元)': 'long_amount',
    '空方未平倉口數': 'short_oi',
    '空方未平倉契約金額(千元)': 'short_amount',
    '多空未平倉口數淨額': 'net_oi',
    '多空未平倉契約金額淨額(千元)': 'net_amount',
}


def _to_int(value) -> Optional[int]:
    text = str(value or '').replace(',', '').strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_csv(text: str, commodity: str = 'TXF') -> list:
    """
    解析期交所 CSV，只留外資那一列。

    Returns:
        list[dict]: [{'trade_date': 'YYYY-MM-DD', 'commodity', 'long_oi', 'short_oi', 'net_oi', ...}]
    """
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    header = None
    rows = []

    for raw in reader:
        cells = [c.strip() for c in raw]
        if not any(cells):
            continue
        if header is None:
            if '身份別' in cells and '日期' in cells:
                header = cells
            continue
        if len(cells) < len(header):
            continue

        record = dict(zip(header, cells))
        # 舊資料寫「外資」，2015 之後是「外資及陸資」
        if '外資' not in record.get('身份別', ''):
            continue

        try:
            trade_date = datetime.strptime(record['日期'], '%Y/%m/%d').date().isoformat()
        except ValueError:
            continue

        row = {'trade_date': trade_date, 'commodity': commodity}
        for column, key in OI_COLUMNS.items():
            row[key] = _to_int(record.get(column))
        if row['long_oi'] is None or row['short_oi'] is None:
            continue
        if row['net_oi'] is None:
            row['net_oi'] = row['long_oi'] - row['short_oi']
        rows.append(row)

    if header is None and text.strip():
        # 期交所查無資料或查詢錯誤時回的是 HTML 頁面，不是 CSV
        print(f"[ForeignFutures] Unexpected response (not CSV): {text[:120]!r}", flush=True)

    return rows


def fetch_range(start: date, end: date, commodity: str = 'TXF') -> list:
    """向期交所下載 [start, end] 區間的 CSV 並解析。"""
    response = requests.post(
        TAIFEX_DOWNLOAD_URL,
        data={
            'queryStartDate': start.strftime('%Y/%m/%d'),
            'queryEndDate': end.strftime('%Y/%m/%d'),
            'commodityId': commodity,
        },
        headers={'User-Agent': 'Mozilla/5.0 (TradingSys foreign futures sync)'},
        timeout=30,
    )
    response.raise_for_status()
    text = response.content.decode('cp950', errors='replace')
    return parse_csv(text, commodity=commodity)


def sync_foreign_futures(commodity: str = None, backfill_days: int = DEFAULT_BACKFILL_DAYS,
                         today: date = None, start: date = None) -> int:
    """
    從資料庫最後一天的隔天抓到今天；資料庫是空的就往回補 backfill_days 天。
    指定 start 時強制從那天重抓（已存在的日期會覆寫）。

    Returns:
        int: 寫入（新增或更新）的筆數
    """
    commodity = commodity or Config.FOREIGN_FUTURES_COMMODITY
    today = today or date.today()

    if start is None:
        latest = get_latest_foreign_futures_date(commodity)
        if latest:
            start = date.fromisoformat(latest) + timedelta(days=1)
        else:
            start = today - timedelta(days=backfill_days)

    saved = 0
    while start <= today:
        end = min(start + timedelta(days=CHUNK_DAYS - 1), today)
        rows = fetch_range(start, end, commodity)
        saved += upsert_foreign_futures(rows)
        start = end + timedelta(days=1)
        if start <= today:
            time.sleep(1)  # 分段補資料時別打太快

    print(f"[ForeignFutures] Synced {commodity}: {saved} rows", flush=True)
    return saved


def main():
    parser = argparse.ArgumentParser(description='同步期交所外資期貨未平倉資料')
    parser.add_argument('--commodity', default=None, help='期貨商品代號，預設 FOREIGN_FUTURES_COMMODITY（TXF）')
    parser.add_argument('--backfill', type=int, default=None,
                        help='強制從 N 天前重抓到今天；不給就只補資料庫最後一天之後的部分')
    args = parser.parse_args()

    from app.models import init_db
    init_db()
    start = date.today() - timedelta(days=args.backfill) if args.backfill else None
    sync_foreign_futures(commodity=args.commodity, start=start)


if __name__ == '__main__':
    main()
