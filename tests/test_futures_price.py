import unittest

from app.services import futures_price

HEADER = ('交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,'
          '最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量')
CSV = '\n'.join([
    HEADER,
    '2026/10/05,TX,202610     ,22800,22950,22750,22900,100,0.44%,"80,000",22905,"95,000",-,-,-,-,,一般,0',
    '2026/10/05,TX,202611     ,22850,23000,22800,22950,100,0.44%,"5,000",22955,"8,000",-,-,-,-,,一般,0',
    '2026/10/05,TX,202610/202611,50,50,50,50,-,-,10,-,-,-,-,-,-,,一般,0',
    '2026/10/05,TX,202610     ,22900,22990,22880,22960,60,0.26%,"30,000",-,-,-,-,-,-,,盤後,0',
    '2026/10/05,MTX,202610     ,1,1,1,1,1,1,1,1,1,-,-,-,-,,一般,0',
])


class ParseTests(unittest.TestCase):
    def test_keeps_near_month_regular_session_only(self):
        rows = futures_price.parse_daily_futures(CSV)

        self.assertEqual(rows, [{
            'trade_date': '2026-10-05', 'commodity': 'TX', 'contract_month': '202610',
            'open': 22800.0, 'high': 22950.0, 'low': 22750.0, 'close': 22900.0, 'settle': 22905.0,
            'volume': 80000, 'open_interest': 95000,
        }])


if __name__ == '__main__':
    unittest.main()
