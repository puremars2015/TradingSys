"""
Futures Price Service — 台指期（TX）每日近月行情。

來源：期交所「期貨每日交易行情」下載端點 futDataDown（Big5 CSV），欄位：

    交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,
    未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,…

每天只留「一般交易時段」的近月合約（到期月份最小的單月合約，價差合約如 202610/202611 不算）。

手動補歷史資料：
    python -m app.services.futures_price --backfill 365
"""

import argparse
from datetime import date, datetime, timedelta

from app.models import get_latest_futures_price_date, upsert_futures_price
from app.services.taifex_client import column, post_csv, read_rows, sync_by_chunks, to_int, to_number

FUT_DAILY_URL = 'https://www.taifex.com.tw/cht/3/futDataDown'
COMMODITY = 'TX'
DEFAULT_BACKFILL_DAYS = 365


def parse_daily_futures(text: str, commodity: str = COMMODITY) -> list:
    """
    Returns:
        list[dict]: 每個交易日一筆近月合約
            {'trade_date', 'commodity', 'contract_month', 'open', 'high', 'low', 'close', 'settle', 'volume', 'open_interest'}
    """
    records = read_rows(text, ('交易日期', '契約'))
    if not records:
        return []
    keys = list(records[0].keys())
    expiry_col = column(keys, '到期月份')
    session_col = column(keys, '交易時段')
    if not expiry_col:
        print(f"[FuturesPrice] Unexpected columns: {keys}", flush=True)
        return []

    nearest = {}
    for record in records:
        if record.get('契約', '').strip() != commodity:
            continue
        if session_col and '盤後' in record.get(session_col, ''):
            continue
        contract_month = record.get(expiry_col, '').replace(' ', '')
        if not (len(contract_month) == 6 and contract_month.isdigit()):
            continue  # 價差合約或週合約
        try:
            trade_date = datetime.strptime(record.get('交易日期', '').strip(), '%Y/%m/%d').date().isoformat()
        except ValueError:
            continue
        close = to_number(record.get(column(keys, '收盤價')))
        settle = to_number(record.get(column(keys, '結算價')))
        if close is None and settle is None:
            continue
        current = nearest.get(trade_date)
        if current and current['contract_month'] <= contract_month:
            continue
        nearest[trade_date] = {
            'trade_date': trade_date,
            'commodity': commodity,
            'contract_month': contract_month,
            'open': to_number(record.get(column(keys, '開盤價'))),
            'high': to_number(record.get(column(keys, '最高價'))),
            'low': to_number(record.get(column(keys, '最低價'))),
            'close': close,
            'settle': settle,
            'volume': to_int(record.get(column(keys, '成交量'))),
            'open_interest': to_int(record.get(column(keys, '未沖銷契約數'))),
        }

    return sorted(nearest.values(), key=lambda r: r['trade_date'])


def fetch_daily_futures(start: date, end: date) -> list:
    text = post_csv(FUT_DAILY_URL, {
        'down_type': '1',
        'commodity_id': COMMODITY,
        'commodity_id2': '',
        'queryStartDate': start.strftime('%Y/%m/%d'),
        'queryEndDate': end.strftime('%Y/%m/%d'),
    })
    return parse_daily_futures(text)


def sync_futures_price(today: date = None, start: date = None,
                       backfill_days: int = DEFAULT_BACKFILL_DAYS) -> int:
    today = today or date.today()
    if start is None:
        latest = get_latest_futures_price_date(COMMODITY)
        start = date.fromisoformat(latest) + timedelta(days=1) if latest else today - timedelta(days=backfill_days)
    return sync_by_chunks(fetch_daily_futures, upsert_futures_price, start, today, 30, 'FuturesPrice')


def main():
    parser = argparse.ArgumentParser(description='同步期交所台指期近月每日行情')
    parser.add_argument('--backfill', type=int, default=None,
                        help='強制從 N 天前重抓到今天；不給就只補資料庫最後一天之後的部分')
    args = parser.parse_args()

    from app.models import init_db
    init_db()
    start = date.today() - timedelta(days=args.backfill) if args.backfill else None
    sync_futures_price(start=start)


if __name__ == '__main__':
    main()
