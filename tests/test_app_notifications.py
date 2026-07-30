import unittest
from unittest.mock import patch

from app.app import _async_notify


class AsyncNotificationTests(unittest.TestCase):
    @patch('app.app.send_trading_notification')
    @patch('app.app.generate_recommendation_message')
    def test_no_recommendation_still_sends_primary_raw_data(
        self, generate_recommendation_message, send_trading_notification
    ):
        data = {
            'symbol': 'TXF1!',
            'price': 42100.0,
            'kd': {
                '1h': {'k': 40.0, 'd': 50.0, 'dir': '空'},
                '4h': {'k': 55.0, 'd': 45.0, 'dir': '多'},
                '1d': {'k': 35.0, 'd': 45.0, 'dir': '空'},
            },
            'sma': {
                'sma10': 42100.0,
                'sma60': 42200.0,
                'sma120': 42300.0,
                'sma720': 42400.0,
            },
        }
        result = {
            'recommendation': '無',
            'signal_strength': '無',
            'trigger': '無交叉',
            'should_notify': False,
        }

        _async_notify(data, result)

        generate_recommendation_message.assert_not_called()
        send_trading_notification.assert_called_once_with(
            symbol='TXF1!',
            price=42100.0,
            recommendation='無',
            signal_strength='無',
            kd_data=data['kd'],
            secondary_message=None,
            send_secondary=False,
            sma_data=data['sma'],
            trigger='無交叉',
        )


if __name__ == '__main__':
    unittest.main()
