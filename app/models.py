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

    conn.commit()
    conn.close()


def save_signal(data: dict, recommendation: str = None, signal_strength: str = None, alert_group: str = 'unknown') -> int:
    """
    Save trading signal to database
    
    Args:
        data: Signal data from TradingView
        recommendation: Analysis recommendation (做多/做空/無)
        signal_strength: Signal strength (無/建議/積極/強烈)
    
    Returns:
        int: Last inserted row ID
    """
    conn = get_db()
    cursor = conn.cursor()
    
    kd = data.get('kd', {})
    
    cursor.execute('''
        INSERT INTO trading_signals (
            received_at, symbol, price, alert_group,
            k_5m, d_5m, dir_5m,
            k_30m, d_30m, dir_30m,
            k_60m, d_60m, dir_60m,
            k_4h, d_4h, dir_4h,
            k_1d, d_1d, dir_1d,
            recommendation, signal_strength, raw_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().isoformat(),
        data.get('symbol'),
        data.get('price'),
        alert_group,
        kd.get('5m', {}).get('k'),
        kd.get('5m', {}).get('d'),
        kd.get('5m', {}).get('dir'),
        kd.get('30m', {}).get('k'),
        kd.get('30m', {}).get('d'),
        kd.get('30m', {}).get('dir'),
        kd.get('60m', {}).get('k'),
        kd.get('60m', {}).get('d'),
        kd.get('60m', {}).get('dir'),
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
