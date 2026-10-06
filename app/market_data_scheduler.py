"""Background thread that syncs daily market data (TAIEX, foreign futures/options OI) once a trading day."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

from app.config import Config
from app.models import (
    get_latest_foreign_futures_date, get_latest_foreign_options_date, get_latest_option_strike_date,
    get_latest_pc_ratio_date, get_latest_taiex_date,
)
from app.services import options
from app.services.foreign_futures import sync_foreign_futures
from app.services.taiex import sync_taiex

TAIPEI = ZoneInfo('Asia/Taipei')
WINDOW_END_HOUR = 21
CHECK_INTERVAL_SECONDS = 30 * 60

_started = False


@dataclass(frozen=True)
class Job:
    name: str
    # 資料大約幾點公布；從這個時間到 WINDOW_END_HOUR 之間每 30 分鐘檢查一次，抓到今天的就停
    window_start_hour: int
    latest: Callable[[], str | None]
    sync: Callable[[date], int]


def _jobs() -> list[Job]:
    jobs = []
    if Config.TAIEX_ENABLED:
        # 證交所 13:30 收盤，FMTQIK 約 14:00 後更新
        jobs.append(Job('TAIEX', 14, get_latest_taiex_date,
                        lambda today: sync_taiex(today=today)))
    if Config.FOREIGN_FUTURES_ENABLED:
        # 期交所約 15:00 公布當日三大法人資料
        jobs.append(Job('ForeignFutures', 15,
                        lambda: get_latest_foreign_futures_date(Config.FOREIGN_FUTURES_COMMODITY),
                        lambda today: sync_foreign_futures(today=today)))
    if Config.OPTIONS_ENABLED:
        # 選擇權三大法人、P/C 比、每日行情都在 15:00 前後公布
        jobs.append(Job('ForeignOptions', 15,
                        lambda: get_latest_foreign_options_date(options.COMMODITY),
                        lambda today: options.sync_foreign_options(today=today)))
        jobs.append(Job('PCRatio', 15, get_latest_pc_ratio_date,
                        lambda today: options.sync_pc_ratio(today=today)))
        jobs.append(Job('OptionStrikes', 15, get_latest_option_strike_date,
                        lambda today: options.sync_option_strikes(today=today)))
    return jobs


def _should_sync(now: datetime, latest: str | None, window_start_hour: int) -> bool:
    """平日公布時段內，且資料庫還沒有今天的資料時才抓。"""
    if now.weekday() >= 5:
        return False
    if not (window_start_hour <= now.hour < WINDOW_END_HOUR):
        return False
    return latest != now.date().isoformat()


def _sync(job: Job, label: str) -> None:
    try:
        job.sync(datetime.now(TAIPEI).date())
    except Exception as exc:
        print(f'[MarketData-Scheduler] {job.name} {label} sync error: {exc}', flush=True)


def _run(jobs: list[Job]) -> None:
    # 啟動先各補一次（資料庫是空的會往回補一年）
    for job in jobs:
        _sync(job, 'startup')
    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)
        now = datetime.now(TAIPEI)
        for job in jobs:
            if _should_sync(now, job.latest(), job.window_start_hour):
                _sync(job, 'daily')


def start_scheduler() -> None:
    global _started
    if _started:
        return
    jobs = _jobs()
    if not jobs:
        return
    _started = True
    threading.Thread(target=_run, args=(jobs,), name='market-data-scheduler', daemon=True).start()
    print(f"[MarketData-Scheduler] started: {', '.join(j.name for j in jobs)}", flush=True)
