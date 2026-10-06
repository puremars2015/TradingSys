import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch

from app.config import Config
from app import models
from app.market_data_scheduler import TAIPEI, _should_sync
from app.services import foreign_futures

HEADER = (
    '日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),'
    '多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),'
    '空方未平倉口數,空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)'
)
SAMPLE_CSV = '\n'.join([
    HEADER,
    '2026/10/01,臺股期貨,自營商,10000,1,9000,1,1000,1,5000,1,6000,1,-1000,1',
    '2026/10/01,臺股期貨,投信,500,1,400,1,100,1,30000,1,2000,1,28000,1',
    '2026/10/01,臺股期貨,外資及陸資,60000,1,61000,1,-1000,1,"20,500",9000000,"52,300",23000000,"-31,800",-14000000',
    '2026/10/02,臺股期貨,外資及陸資,60000,1,61000,1,-1000,1,21000,1,50000,1,-29000,1',
])


class ParseCsvTests(unittest.TestCase):
    def test_keeps_only_foreign_rows_with_open_interest(self):
        rows = foreign_futures.parse_csv(SAMPLE_CSV)

        self.assertEqual([r['trade_date'] for r in rows], ['2026-10-01', '2026-10-02'])
        self.assertEqual(rows[0]['long_oi'], 20500)
        self.assertEqual(rows[0]['short_oi'], 52300)
        self.assertEqual(rows[0]['net_oi'], -31800)
        self.assertEqual(rows[0]['net_amount'], -14000000)
        self.assertEqual(rows[0]['commodity'], 'TXF')

    def test_html_error_page_returns_no_rows(self):
        self.assertEqual(foreign_futures.parse_csv('<html><body>查無資料</body></html>'), [])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(Config, 'DATABASE_PATH', os.path.join(self.tmp.name, 'test.db'))
        self.db_patch.start()
        models.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    @patch('app.services.foreign_futures.time.sleep')
    @patch('app.services.foreign_futures.fetch_range')
    def test_backfills_in_chunks_then_resumes_after_latest_date(self, fetch_range, _sleep):
        fetch_range.return_value = foreign_futures.parse_csv(SAMPLE_CSV)

        foreign_futures.sync_foreign_futures('TXF', backfill_days=60, today=date(2026, 10, 2))

        # 60 天 → 切成 30 天一段
        self.assertEqual(fetch_range.call_count, 3)
        self.assertEqual(fetch_range.call_args_list[0].args[0], date(2026, 8, 3))
        rows = models.get_foreign_futures('TXF')
        self.assertEqual(len(rows), 2)  # 重複日期覆寫，不會多出來
        self.assertEqual(models.get_latest_foreign_futures_date('TXF'), '2026-10-02')

        fetch_range.reset_mock()
        fetch_range.return_value = []
        foreign_futures.sync_foreign_futures('TXF', today=date(2026, 10, 5))
        fetch_range.assert_called_once_with(date(2026, 10, 3), date(2026, 10, 5), 'TXF')


class SchedulerTests(unittest.TestCase):
    def test_syncs_only_on_weekday_window_when_today_missing(self):
        weekday_4pm = datetime(2026, 10, 6, 16, 0, tzinfo=TAIPEI)  # 週二
        self.assertTrue(_should_sync(weekday_4pm, '2026-10-05', 15))
        self.assertFalse(_should_sync(weekday_4pm, '2026-10-06', 15))
        self.assertFalse(_should_sync(datetime(2026, 10, 6, 14, 30, tzinfo=TAIPEI), '2026-10-05', 15))
        self.assertTrue(_should_sync(datetime(2026, 10, 6, 14, 30, tzinfo=TAIPEI), '2026-10-05', 14))
        self.assertFalse(_should_sync(datetime(2026, 10, 10, 16, 0, tzinfo=TAIPEI), '2026-10-09', 15))


if __name__ == '__main__':
    unittest.main()
