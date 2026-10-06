import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from app import models
from app.config import Config
from app.services import taiex

FIELDS = ['日期', '成交股數', '成交金額', '成交筆數', '發行量加權股價指數', '漲跌點數']


def payload(*rows):
    return {'stat': 'OK', 'fields': FIELDS, 'data': list(rows)}


SEPTEMBER = payload(
    ['115/09/29', '7,000,000,000', '400,000,000,000', '2,000,000', '22,100.50', '-50.25'],
    ['115/09/30', '7,500,000,000', '450,500,000,000', '2,100,000', '22,200.00', '99.50'],
)
OCTOBER = payload(
    ['115/10/01', '8,000,000,000', '500,000,000,000', '2,200,000', '22,300.00', '+100.00'],
)


class ParseTests(unittest.TestCase):
    def test_parses_roc_dates_and_numbers(self):
        rows = taiex.parse_fmtqik(SEPTEMBER)

        self.assertEqual(rows[0], {
            'trade_date': '2026-09-29', 'close': 22100.5, 'change': -50.25,
            'turnover': 400000000000, 'volume_shares': 7000000000, 'transactions': 2000000,
        })
        self.assertEqual(taiex.parse_fmtqik(OCTOBER)[0]['change'], 100.0)

    def test_no_data_returns_empty(self):
        self.assertEqual(taiex.parse_fmtqik({'stat': '很抱歉，沒有符合條件的資料!'}), [])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(Config, 'DATABASE_PATH', os.path.join(self.tmp.name, 'test.db'))
        self.db_patch.start()
        models.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    @patch('app.services.taiex.time.sleep')
    @patch('app.services.taiex.fetch_month')
    def test_backfills_month_by_month_then_resumes(self, fetch_month, _sleep):
        fetch_month.side_effect = lambda month: taiex.parse_fmtqik(
            {9: SEPTEMBER, 10: OCTOBER}.get(month.month, {'stat': 'none'}))

        taiex.sync_taiex(backfill_days=40, today=date(2026, 10, 1))

        self.assertEqual([c.args[0] for c in fetch_month.call_args_list],
                         [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)])
        self.assertEqual([r['trade_date'] for r in models.get_taiex()],
                         ['2026-09-29', '2026-09-30', '2026-10-01'])

        fetch_month.reset_mock()
        taiex.sync_taiex(today=date(2026, 10, 2))
        # 只重抓最新資料所在的月份
        self.assertEqual([c.args[0] for c in fetch_month.call_args_list], [date(2026, 10, 1)])
        self.assertEqual(len(models.get_taiex()), 3)


if __name__ == '__main__':
    unittest.main()
