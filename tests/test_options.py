import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from app import models
from app.config import Config
from app.services import options

INSTITUTIONAL_CSV = '\n'.join([
    '日期,商品名稱,買賣權別,身份別,買方交易口數,買方交易契約金額(千元),賣方交易口數,賣方交易契約金額(千元),'
    '交易口數買賣淨額,交易契約金額買賣淨額(千元),買方未平倉口數,買方未平倉契約金額(千元),賣方未平倉口數,'
    '賣方未平倉契約金額(千元),未平倉口數買賣淨額,未平倉契約金額買賣淨額(千元)',
    '2026/10/05,臺指選擇權,買權,自營商,1,1,1,1,0,0,9,9,9,9,0,0',
    '2026/10/05,臺指選擇權,買權,外資及陸資,1,1,1,1,0,0,"30,000","1,200,000","25,000","900,000",5000,300000',
    '2026/10/05,臺指選擇權,賣權,外資及陸資,1,1,1,1,0,0,"20,000","500,000","28,000","700,000",-8000,-200000',
])

PC_CSV = '\n'.join([
    '日期,賣權成交量,買權成交量,買賣權成交量比率%,賣權未平倉量,買權未平倉量,買賣權未平倉量比率%',
    '2026/10/05,"500,000","450,000",111.11,"130,000","100,000",130.00',
])

DAILY_CSV = '\n'.join([
    '交易日期,契約,到期月份(週別),履約價,買賣權,開盤價,最高價,最低價,收盤價,成交量,結算價,未沖銷契約數,'
    '最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,漲跌價,漲跌%',
    '2026/10/05,TXO,202610  ,22000,買權,1,1,1,1,1,350,"8,000",-,-,-,-,,一般,1,1',
    '2026/10/05,TXO,202610  ,22000,賣權,1,1,1,1,1,120,"12,000",-,-,-,-,,一般,1,1',
    '2026/10/05,TXO,202610  ,22000,買權,1,1,1,1,1,-,-,-,-,-,-,,盤後,1,1',
    '2026/10/05,TXO,202610W2,22100,買權,1,1,1,1,1,80,"3,000",-,-,-,-,,一般,1,1',
    '2026/10/05,TEO,202610  ,1000,買權,1,1,1,1,1,1,1,-,-,-,-,,一般,1,1',
])


class ParseTests(unittest.TestCase):
    def test_institutional_keeps_foreign_call_and_put_in_one_row(self):
        rows = options.parse_institutional(INSTITUTIONAL_CSV)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['trade_date'], '2026-10-05')
        self.assertEqual((row['call_buy_oi'], row['call_sell_oi']), (30000, 25000))
        self.assertEqual((row['call_buy_amount'], row['call_sell_amount']), (1200000, 900000))
        self.assertEqual((row['put_buy_oi'], row['put_sell_oi']), (20000, 28000))

    def test_pc_ratio(self):
        self.assertEqual(options.parse_pc_ratio(PC_CSV), [{
            'trade_date': '2026-10-05', 'put_volume': 500000, 'call_volume': 450000, 'volume_ratio': 111.11,
            'put_oi': 130000, 'call_oi': 100000, 'oi_ratio': 130.0,
        }])

    def test_daily_options_merges_call_put_and_skips_after_hours(self):
        rows = {(r['expiry'], r['strike']): r for r in options.parse_daily_options(DAILY_CSV)}

        self.assertEqual(set(rows), {('202610', 22000.0), ('202610W2', 22100.0)})
        self.assertEqual(rows[('202610', 22000.0)]['call_oi'], 8000)
        self.assertEqual(rows[('202610', 22000.0)]['put_oi'], 12000)
        self.assertEqual(rows[('202610', 22000.0)]['call_settle'], 350.0)

    def test_expiry_dates(self):
        self.assertEqual(options.expiry_date('202610'), date(2026, 10, 21))    # 第三個週三
        self.assertEqual(options.expiry_date('202610W1'), date(2026, 10, 7))
        self.assertEqual(options.expiry_date('202610F2'), date(2026, 10, 9))   # 第二個週五
        self.assertIsNone(options.expiry_date('weird'))


class StrikesApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(Config, 'DATABASE_PATH', os.path.join(self.tmp.name, 'test.db'))
        self.db_patch.start()
        models.init_db()
        from app.app import app
        self.client = app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_defaults_to_nearest_monthly_and_reports_change(self):
        def row(d, expiry, strike, call, put):
            return {'trade_date': d, 'expiry': expiry, 'strike': strike, 'call_oi': call, 'put_oi': put}
        models.upsert_option_strikes([
            row('2026-10-02', '202610', 22000, 7000, 11000),
            row('2026-10-05', '202610', 22000, 8000, 12000),
            row('2026-10-05', '202610W1', 22000, 100, 100),   # 已到期的週選
            row('2026-10-05', '202610W2', 22000, 500, 400),
            row('2026-10-05', '202611', 22000, 900, 800),
        ])

        data = self.client.get('/api/options/strikes').get_json()

        self.assertEqual(data['date'], '2026-10-05')
        self.assertEqual(data['expiry'], '202610')
        self.assertEqual([e['code'] for e in data['expiries']], ['202610W1', '202610W2', '202610', '202611'])
        self.assertEqual(data['rows'][0]['call_oi_change'], 1000)
        self.assertEqual(data['rows'][0]['put_oi_change'], 1000)

        data = self.client.get('/api/options/strikes?expiry=202610W2').get_json()
        self.assertEqual(data['expiry'], '202610W2')
        self.assertIsNone(data['rows'][0]['call_oi_change'])


if __name__ == '__main__':
    unittest.main()
