import unittest

from app.services.telegram_bot import format_trading_signal


class TelegramFormattingTests(unittest.TestCase):
    def test_primary_bearish_sma_comparison_is_html_escaped(self):
        message = format_trading_signal(
            symbol='TXF1!',
            price=None,
            recommendation='做多',
            signal_strength='建議',
            kd_data={
                '1h': {'k': 30.81, 'd': 31.84, 'dir': '空'},
                '4h': {'k': 23.32, 'd': 18.87, 'dir': '多'},
                '1d': {'k': 22.72, 'd': 30.05, 'dir': '空'},
            },
            sma_data={
                'sma10': 41748.0,
                'sma60': 43097.0,
                'sma120': 43816.0,
                'sma720': 45310.0,
            },
        )

        self.assertIn('排列: 空頭排列 (10&lt;60&lt;120&lt;720)', message)
        self.assertNotIn('(10<60<120<720)', message)


if __name__ == '__main__':
    unittest.main()
