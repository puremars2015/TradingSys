import sqlite3
import json
from datetime import datetime, timedelta
from app.config import Config


def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database with trading_signals table and lightweight migrations."""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trading_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL,
            alert_group TEXT DEFAULT 'unknown',
            sma10 REAL,
            sma60 REAL,
            sma120 REAL,
            sma720 REAL,
            k_5m REAL, d_5m REAL, dir_5m TEXT,
            k_30m REAL, d_30m REAL, dir_30m TEXT,
            k_60m REAL, d_60m REAL, dir_60m TEXT,
            k_4h REAL, d_4h REAL, dir_4h TEXT,
            k_1d REAL, d_1d REAL, dir_1d TEXT,
            recommendation TEXT,
            signal_strength TEXT,
            raw_data TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    columns = {row[1] for row in conn.execute("PRAGMA table_info(trading_signals)").fetchall()}
    if 'alert_group' not in columns:
        conn.execute("ALTER TABLE trading_signals ADD COLUMN alert_group TEXT DEFAULT 'unknown'")
        conn.execute(
            "UPDATE trading_signals SET alert_group = CASE "
            "WHEN k_5m IS NOT NULL OR k_30m IS NOT NULL THEN 'intraday' "
            "WHEN k_4h IS NOT NULL OR k_1d IS NOT NULL THEN 'swing' "
            "ELSE 'unknown' END "
            "WHERE alert_group IS NULL OR alert_group = '' OR alert_group = 'unknown'"
        )
    if 'sma10' not in columns:
        conn.execute("ALTER TABLE trading_signals ADD COLUMN sma10 REAL")
    if 'sma60' not in columns:
        conn.execute("ALTER TABLE trading_signals ADD COLUMN sma60 REAL")
    if 'sma120' not in columns:
        conn.execute("ALTER TABLE trading_signals ADD COLUMN sma120 REAL")
    if 'sma720' not in columns:
        conn.execute("ALTER TABLE trading_signals ADD COLUMN sma720 REAL")

    # 外資期貨未平倉（每日一筆，來源：期交所三大法人 - 區分各期貨契約）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS foreign_futures_oi (
            trade_date TEXT NOT NULL,
            commodity TEXT NOT NULL,
            long_oi INTEGER,
            long_amount INTEGER,
            short_oi INTEGER,
            short_amount INTEGER,
            net_oi INTEGER,
            net_amount INTEGER,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, commodity)
        )
    ''')

    # 加權指數與每日成交量（來源：證交所 FMTQIK）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS taiex_daily (
            trade_date TEXT PRIMARY KEY,
            close REAL,
            change REAL,
            turnover INTEGER,
            volume_shares INTEGER,
            transactions INTEGER,
            updated_at TEXT NOT NULL
        )
    ''')

    # 外資台指選擇權留倉（期交所三大法人 - 選擇權買賣權分計），金額單位千元
    conn.execute('''
        CREATE TABLE IF NOT EXISTS foreign_options_oi (
            trade_date TEXT NOT NULL,
            commodity TEXT NOT NULL,
            call_buy_oi INTEGER, call_buy_amount INTEGER,
            call_sell_oi INTEGER, call_sell_amount INTEGER,
            put_buy_oi INTEGER, put_buy_amount INTEGER,
            put_sell_oi INTEGER, put_sell_amount INTEGER,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, commodity)
        )
    ''')

    # 台指期近月每日行情（一般交易時段，來源：期交所 futDataDown）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS futures_daily (
            trade_date TEXT NOT NULL,
            commodity TEXT NOT NULL,
            contract_month TEXT,
            open REAL, high REAL, low REAL, close REAL, settle REAL,
            volume INTEGER, open_interest INTEGER,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, commodity)
        )
    ''')

    # 台指選擇權全市場 Put/Call 比（ratio 單位為 %）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS options_pc_ratio (
            trade_date TEXT PRIMARY KEY,
            put_volume INTEGER, call_volume INTEGER, volume_ratio REAL,
            put_oi INTEGER, call_oi INTEGER, oi_ratio REAL,
            updated_at TEXT NOT NULL
        )
    ''')

    # 台指選擇權各履約價未平倉（一般交易時段）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS option_strike_oi (
            trade_date TEXT NOT NULL,
            expiry TEXT NOT NULL,
            strike REAL NOT NULL,
            call_oi INTEGER, put_oi INTEGER,
            call_settle REAL, put_settle REAL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, expiry, strike)
        )
    ''')

    conn.commit()
    conn.close()


def save_signal(data: dict, recommendation: str = None, signal_strength: str = None, alert_group: str = 'unknown') -> int:
    """
    Save trading signal to database

    1H 的 K/D 沿用既有的 k_60m/d_60m/dir_60m 欄位（同一組指標，只是換了命名），
    舊的 5m/30m 欄位保留在資料表裡給歷史資料用，新訊號不再寫入。

    Args:
        data: Parsed signal data (見 signal_analyzer.parse_payload)
        recommendation: Analysis recommendation (做多/做空/持有/無)
        signal_strength: Signal strength (無/建議/積極/強烈/持續)

    Returns:
        int: Last inserted row ID
    """
    conn = get_db()
    cursor = conn.cursor()

    kd = data.get('kd', {})
    sma = data.get('sma', {})

    cursor.execute('''
        INSERT INTO trading_signals (
            received_at, symbol, price, alert_group,
            sma10, sma60, sma120, sma720,
            k_60m, d_60m, dir_60m,
            k_4h, d_4h, dir_4h,
            k_1d, d_1d, dir_1d,
            recommendation, signal_strength, raw_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().isoformat(),
        data.get('symbol'),
        data.get('price'),
        alert_group,
        sma.get('sma10'),
        sma.get('sma60'),
        sma.get('sma120'),
        sma.get('sma720'),
        kd.get('1h', {}).get('k'),
        kd.get('1h', {}).get('d'),
        kd.get('1h', {}).get('dir'),
        kd.get('4h', {}).get('k'),
        kd.get('4h', {}).get('d'),
        kd.get('4h', {}).get('dir'),
        kd.get('1d', {}).get('k'),
        kd.get('1d', {}).get('d'),
        kd.get('1d', {}).get('dir'),
        recommendation,
        signal_strength,
        json.dumps(data)
    ))

    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_latest_signal(symbol: str = None) -> dict:
    """Get the latest signal record"""
    conn = get_db()
    cursor = conn.cursor()

    if symbol:
        cursor.execute(
            'SELECT * FROM trading_signals WHERE symbol = ? ORDER BY id DESC LIMIT 1',
            (symbol,)
        )
    else:
        cursor.execute('SELECT * FROM trading_signals ORDER BY id DESC LIMIT 1')

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def get_previous_signal(symbol: str = None, before_id: int = None, alert_group: str = None) -> dict:
    """Get the previous signal record before the given ID, optionally filtered by alert group."""
    conn = get_db()
    cursor = conn.cursor()

    group_clause = ""
    params = []
    if alert_group:
        group_clause = " AND alert_group = ?"
        params.append(alert_group)

    if symbol and before_id:
        cursor.execute(f'''
            SELECT * FROM trading_signals
            WHERE symbol = ? AND id < ?{group_clause}
            ORDER BY id DESC LIMIT 1
        ''', (symbol, before_id, *params))
        rows = cursor.fetchall()
        conn.close()
        return dict(rows[0]) if len(rows) > 0 else None
    elif symbol:
        cursor.execute(f'''
            SELECT * FROM trading_signals
            WHERE symbol = ?{group_clause}
            ORDER BY id DESC LIMIT 1
        ''', (symbol, *params))
        rows = cursor.fetchall()
        conn.close()
        return dict(rows[0]) if len(rows) > 0 else None
    elif before_id:
        cursor.execute('''
            SELECT * FROM trading_signals
            WHERE id < ?
            ORDER BY id DESC LIMIT 1
        ''', (before_id,))
        rows = cursor.fetchall()
        conn.close()
        return dict(rows[0]) if len(rows) > 0 else None
    else:
        cursor.execute('''
            SELECT * FROM trading_signals
            ORDER BY id DESC LIMIT 2
        ''')
        rows = cursor.fetchall()
        conn.close()
        return dict(rows[1]) if len(rows) > 1 else None


def has_recent_duplicate_notification(
    symbol: str,
    alert_group: str,
    recommendation: str,
    signal_strength: str,
    *,
    exclude_id: int | None = None,
    within_seconds: int = 60,
) -> bool:
    """Return True when an equivalent notifiable signal already exists within the recent window."""
    conn = get_db()
    cursor = conn.cursor()
    threshold = (datetime.now() - timedelta(seconds=within_seconds)).isoformat()

    query = '''
        SELECT 1
        FROM trading_signals
        WHERE symbol = ?
          AND alert_group = ?
          AND recommendation = ?
          AND signal_strength = ?
          AND received_at >= ?
    '''
    params = [symbol, alert_group, recommendation, signal_strength, threshold]

    if exclude_id is not None:
        query += ' AND id != ?'
        params.append(exclude_id)

    query += ' ORDER BY id DESC LIMIT 1'
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_recent_signals(symbol: str = None, limit: int = 10) -> list:
    """Get recent signal records"""
    conn = get_db()
    cursor = conn.cursor()

    if symbol:
        cursor.execute(
            'SELECT * FROM trading_signals WHERE symbol = ? ORDER BY id DESC LIMIT ?',
            (symbol, limit)
        )
    else:
        cursor.execute(
            'SELECT * FROM trading_signals ORDER BY id DESC LIMIT ?',
            (limit,)
        )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_all_signals(symbol: str = None) -> list:
    """Get ALL signal records (no limit), newest first."""
    conn = get_db()
    cursor = conn.cursor()

    if symbol:
        cursor.execute(
            'SELECT * FROM trading_signals WHERE symbol = ? ORDER BY id DESC',
            (symbol,)
        )
    else:
        cursor.execute('SELECT * FROM trading_signals ORDER BY id DESC')

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_signals_count(symbol: str = None) -> int:
    """Total number of signal records (optionally filtered by symbol)."""
    conn = get_db()
    cursor = conn.cursor()

    if symbol:
        cursor.execute(
            'SELECT COUNT(*) FROM trading_signals WHERE symbol = ?', (symbol,)
        )
    else:
        cursor.execute('SELECT COUNT(*) FROM trading_signals')

    total = cursor.fetchone()[0]
    conn.close()
    return total


def get_signals_page(symbol: str = None, page: int = 1, per_page: int = 50) -> list:
    """Get one page of signal records, newest first."""
    page = max(1, page)
    offset = (page - 1) * per_page
    conn = get_db()
    cursor = conn.cursor()

    if symbol:
        cursor.execute(
            'SELECT * FROM trading_signals WHERE symbol = ? '
            'ORDER BY id DESC LIMIT ? OFFSET ?',
            (symbol, per_page, offset)
        )
    else:
        cursor.execute(
            'SELECT * FROM trading_signals ORDER BY id DESC LIMIT ? OFFSET ?',
            (per_page, offset)
        )

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def upsert_foreign_futures(rows: list) -> int:
    """寫入外資期貨未平倉資料；同一天同商品重抓時覆寫。回傳寫入筆數。"""
    if not rows:
        return 0
    now = datetime.now().isoformat()
    conn = get_db()
    conn.executemany('''
        INSERT INTO foreign_futures_oi (
            trade_date, commodity, long_oi, long_amount, short_oi, short_amount,
            net_oi, net_amount, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, commodity) DO UPDATE SET
            long_oi = excluded.long_oi,
            long_amount = excluded.long_amount,
            short_oi = excluded.short_oi,
            short_amount = excluded.short_amount,
            net_oi = excluded.net_oi,
            net_amount = excluded.net_amount,
            updated_at = excluded.updated_at
    ''', [
        (r['trade_date'], r['commodity'], r.get('long_oi'), r.get('long_amount'),
         r.get('short_oi'), r.get('short_amount'), r.get('net_oi'), r.get('net_amount'), now)
        for r in rows
    ])
    conn.commit()
    conn.close()
    return len(rows)


def get_latest_foreign_futures_date(commodity: str) -> str | None:
    """資料庫裡該商品最新一筆的交易日（YYYY-MM-DD），沒有資料回 None。"""
    conn = get_db()
    row = conn.execute(
        'SELECT MAX(trade_date) FROM foreign_futures_oi WHERE commodity = ?', (commodity,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_foreign_futures(commodity: str, days: int | None = None) -> list:
    """取外資期貨未平倉資料，依日期由舊到新；days 為往回幾個日曆天，None 表示全部。"""
    conn = get_db()
    if days:
        since = (datetime.now() - timedelta(days=days)).date().isoformat()
        rows = conn.execute(
            'SELECT * FROM foreign_futures_oi WHERE commodity = ? AND trade_date >= ? '
            'ORDER BY trade_date',
            (commodity, since)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM foreign_futures_oi WHERE commodity = ? ORDER BY trade_date',
            (commodity,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def upsert_taiex(rows: list) -> int:
    """寫入加權指數每日資料；同一天重抓時覆寫。回傳寫入筆數。"""
    if not rows:
        return 0
    now = datetime.now().isoformat()
    conn = get_db()
    conn.executemany('''
        INSERT INTO taiex_daily (
            trade_date, close, change, turnover, volume_shares, transactions, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            close = excluded.close,
            change = excluded.change,
            turnover = excluded.turnover,
            volume_shares = excluded.volume_shares,
            transactions = excluded.transactions,
            updated_at = excluded.updated_at
    ''', [
        (r['trade_date'], r.get('close'), r.get('change'), r.get('turnover'),
         r.get('volume_shares'), r.get('transactions'), now)
        for r in rows
    ])
    conn.commit()
    conn.close()
    return len(rows)


def get_latest_taiex_date() -> str | None:
    """資料庫裡加權指數最新一筆的交易日（YYYY-MM-DD），沒有資料回 None。"""
    conn = get_db()
    row = conn.execute('SELECT MAX(trade_date) FROM taiex_daily').fetchone()
    conn.close()
    return row[0] if row else None


def get_taiex(days: int | None = None) -> list:
    """取加權指數每日資料，依日期由舊到新；days 為往回幾個日曆天，None 表示全部。"""
    conn = get_db()
    if days:
        since = (datetime.now() - timedelta(days=days)).date().isoformat()
        rows = conn.execute(
            'SELECT * FROM taiex_daily WHERE trade_date >= ? ORDER BY trade_date', (since,)
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM taiex_daily ORDER BY trade_date').fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _upsert(table: str, keys: tuple, columns: tuple, rows: list) -> int:
    """依主鍵 keys 寫入或覆寫 columns，附上 updated_at。回傳寫入筆數。"""
    if not rows:
        return 0
    names = keys + columns + ('updated_at',)
    updates = ', '.join(f'{c} = excluded.{c}' for c in columns + ('updated_at',))
    now = datetime.now().isoformat()
    conn = get_db()
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)}) "
        f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET {updates}",
        [tuple(r.get(n) for n in keys + columns) + (now,) for r in rows]
    )
    conn.commit()
    conn.close()
    return len(rows)


def _latest_date(table: str, where: str = '', params: tuple = ()) -> str | None:
    conn = get_db()
    row = conn.execute(f'SELECT MAX(trade_date) FROM {table} {where}', params).fetchone()
    conn.close()
    return row[0] if row else None


def _rows_since(table: str, days: int | None, where: str = '', params: tuple = ()) -> list:
    clauses = [where] if where else []
    params = list(params)
    if days:
        clauses.append('trade_date >= ?')
        params.append((datetime.now() - timedelta(days=days)).date().isoformat())
    sql = f"SELECT * FROM {table}" + (f" WHERE {' AND '.join(clauses)}" if clauses else '') + ' ORDER BY trade_date'
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


FOREIGN_OPTIONS_COLUMNS = (
    'call_buy_oi', 'call_buy_amount', 'call_sell_oi', 'call_sell_amount',
    'put_buy_oi', 'put_buy_amount', 'put_sell_oi', 'put_sell_amount',
)


def upsert_foreign_options(rows: list) -> int:
    return _upsert('foreign_options_oi', ('trade_date', 'commodity'), FOREIGN_OPTIONS_COLUMNS, rows)


def get_latest_foreign_options_date(commodity: str) -> str | None:
    return _latest_date('foreign_options_oi', 'WHERE commodity = ?', (commodity,))


def get_foreign_options(commodity: str, days: int | None = None) -> list:
    return _rows_since('foreign_options_oi', days, 'commodity = ?', (commodity,))


def upsert_pc_ratio(rows: list) -> int:
    return _upsert('options_pc_ratio', ('trade_date',),
                   ('put_volume', 'call_volume', 'volume_ratio', 'put_oi', 'call_oi', 'oi_ratio'), rows)


def get_latest_pc_ratio_date() -> str | None:
    return _latest_date('options_pc_ratio')


def get_pc_ratio(days: int | None = None) -> list:
    return _rows_since('options_pc_ratio', days)


def upsert_option_strikes(rows: list) -> int:
    return _upsert('option_strike_oi', ('trade_date', 'expiry', 'strike'),
                   ('call_oi', 'put_oi', 'call_settle', 'put_settle'), rows)


def get_latest_option_strike_date() -> str | None:
    return _latest_date('option_strike_oi')


def get_option_strike_dates(limit: int = 30) -> list:
    """有履約價資料的交易日，新到舊。"""
    conn = get_db()
    rows = conn.execute(
        'SELECT DISTINCT trade_date FROM option_strike_oi ORDER BY trade_date DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_option_expiries(trade_date: str) -> list:
    """某交易日的到期代號與各自的 Call/Put 未平倉總量。"""
    conn = get_db()
    rows = conn.execute('''
        SELECT expiry, SUM(COALESCE(call_oi, 0)) AS call_oi, SUM(COALESCE(put_oi, 0)) AS put_oi
        FROM option_strike_oi WHERE trade_date = ? GROUP BY expiry
    ''', (trade_date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_option_strikes(trade_date: str, expiry: str) -> list:
    """某交易日、某到期的各履約價未平倉，附上與前一個交易日相比的增減。"""
    conn = get_db()
    prev = conn.execute(
        'SELECT MAX(trade_date) FROM option_strike_oi WHERE trade_date < ? AND expiry = ?',
        (trade_date, expiry)
    ).fetchone()[0]
    rows = conn.execute('''
        SELECT cur.strike, cur.call_oi, cur.put_oi, cur.call_settle, cur.put_settle,
               cur.call_oi - prev.call_oi AS call_oi_change,
               cur.put_oi - prev.put_oi AS put_oi_change
        FROM option_strike_oi cur
        LEFT JOIN option_strike_oi prev
          ON prev.trade_date = ? AND prev.expiry = cur.expiry AND prev.strike = cur.strike
        WHERE cur.trade_date = ? AND cur.expiry = ?
        ORDER BY cur.strike
    ''', (prev, trade_date, expiry)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_futures_price(rows: list) -> int:
    return _upsert('futures_daily', ('trade_date', 'commodity'),
                   ('contract_month', 'open', 'high', 'low', 'close', 'settle', 'volume', 'open_interest'), rows)


def get_latest_futures_price_date(commodity: str) -> str | None:
    return _latest_date('futures_daily', 'WHERE commodity = ?', (commodity,))


def get_futures_price(commodity: str, days: int | None = None) -> list:
    return _rows_since('futures_daily', days, 'commodity = ?', (commodity,))
