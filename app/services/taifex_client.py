"""
期交所 CSV 下載的共用工具：下載（Big5）、找表頭、數字轉換、分段補資料。
"""

import csv
import io
import time
from datetime import date, timedelta
from typing import Callable, Optional

import requests

USER_AGENT = 'Mozilla/5.0 (TradingSys market data sync)'


def post_csv(url: str, data: dict) -> str:
    """POST 期交所下載端點，回傳解碼後的 CSV 文字。"""
    response = requests.post(url, data=data, headers={'User-Agent': USER_AGENT}, timeout=60)
    response.raise_for_status()
    return response.content.decode('cp950', errors='replace')


def read_rows(text: str, required: tuple) -> list:
    """
    把 CSV 轉成 dict 列表；第一個同時包含 required 欄位的列視為表頭。
    期交所查無資料時回的是 HTML，這時回傳空列表並印出前幾個字。
    """
    header = None
    rows = []
    for raw in csv.reader(io.StringIO(text.lstrip('﻿'))):
        cells = [c.strip() for c in raw]
        if not any(cells):
            continue
        if header is None:
            if all(name in cells for name in required):
                header = cells
            continue
        rows.append(dict(zip(header, cells)))

    if header is None and text.strip():
        print(f"[TAIFEX] Unexpected response (not CSV): {text[:120]!r}", flush=True)
    return rows


def column(header_keys, prefix: str) -> Optional[str]:
    """找第一個以 prefix 開頭的欄位名稱（期交所欄名偶爾會多括號註記）。"""
    return next((k for k in header_keys if k.startswith(prefix)), None)


def to_number(value) -> Optional[float]:
    text = str(value or '').replace(',', '').replace('%', '').replace('+', '').strip()
    if not text or text in ('-', '--'):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value) -> Optional[int]:
    number = to_number(value)
    return int(number) if number is not None else None


def sync_by_chunks(fetch: Callable[[date, date], list], upsert: Callable[[list], int],
                   start: date, today: date, chunk_days: int, label: str) -> int:
    """把 [start, today] 切成 chunk_days 一段逐段抓取寫入，段與段之間稍微停一下。"""
    saved = 0
    while start <= today:
        end = min(start + timedelta(days=chunk_days - 1), today)
        saved += upsert(fetch(start, end))
        start = end + timedelta(days=1)
        if start <= today:
            time.sleep(1)
    print(f"[{label}] Synced: {saved} rows", flush=True)
    return saved
