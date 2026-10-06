"""Background thread that syncs foreign futures open interest from TAIFEX once a day."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Config
from app.models import get_latest_foreign_futures_date
from app.services.foreign_futures import sync_foreign_futures

TAIPEI = ZoneInfo('Asia/Taipei')
# 期交所約 15:00 公布當日三大法人資料；這段時間內每 30 分鐘檢查一次，抓到就停
WINDOW_START_HOUR = 15
WINDOW_END_HOUR = 21
CHECK_INTERVAL_SECONDS = 30 * 60

_started = False


def _sync(label: str) -> None:
    try:
        sync_foreign_futures(today=datetime.now(TAIPEI).date())
    except Exception as exc:
        print(f'[ForeignFutures-Scheduler] {label} sync error: {exc}', flush=True)


def _should_sync(now: datetime, latest: str | None) -> bool:
    """平日公布時段內，且資料庫還沒有今天的資料時才抓。"""
    if now.weekday() >= 5:
        return False
    if not (WINDOW_START_HOUR <= now.hour < WINDOW_END_HOUR):
        return False
    return latest != now.date().isoformat()


def _run() -> None:
    # 啟動先補一次（資料庫是空的會往回補一年）
    _sync('startup')
    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)
        now = datetime.now(TAIPEI)
        if _should_sync(now, get_latest_foreign_futures_date(Config.FOREIGN_FUTURES_COMMODITY)):
            _sync('daily')


def start_scheduler() -> None:
    global _started
    if _started or not Config.FOREIGN_FUTURES_ENABLED:
        return
    _started = True
    threading.Thread(target=_run, name='foreign-futures-scheduler', daemon=True).start()
    print('[ForeignFutures-Scheduler] started', flush=True)
