"""
TradingView Signal Bot - Flask Application

Receives TradingView webhook data, analyzes KD indicators,
and sends notifications via Telegram.
"""

import json
from flask import Flask, request, jsonify, render_template
from app.config import Config
from app.models import init_db, get_latest_signal, get_recent_signals
from app.services.signal_analyzer import process_signal, should_notify
from app.services.telegram_bot import send_trading_notification
from app.services.llm_generator import generate_recommendation_message


def create_app():
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize database on startup
    init_db()
    
    return app


app = create_app()


@app.route('/')
def index():
    """Home page showing recent signals"""
    # Real-time health check
    healthy = False
    db_records = 0
    try:
        recent = get_recent_signals(limit=5)
        latest = get_latest_signal()
        db_records = len(recent)
        healthy = True
    except Exception as e:
        recent = []
        latest = None
        print(f"[Health Check] DB error: {e}")

    return render_template(
        'index.html',
        recent_signals=recent,
        latest_signal=latest,
        healthy=healthy,
        db_records=db_records
    )


@app.route('/api/status')
def status():
    """Health check endpoint"""
    latest = get_latest_signal()
    return jsonify({
        'status': 'ok',
        'service': 'TradingView Signal Bot',
        'latest_signal': latest is not None,
        'database': Config.DATABASE_PATH
    })


@app.route('/webhook/cross-alert-5m-30m-60m', methods=['POST'])
def webhook_5m_30m_60m():
    """
    Receive TradingView alert for 5m/30m/60m timeframes
    
    Expected data format:
    {
        "symbol": "TXF1!",
        "timeframe": "5m",
        "signal": "UP",
        "price": 32875.00,
        "kd": {
            "5m": { "k": 23.45, "d": 31.67, "dir": "空" },
            "30m": { "k": 45.12, "d": 38.90, "dir": "多" },
            "60m": { "k": 61.08, "d": 55.34, "dir": "多" }
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        required = ['symbol', 'kd']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Process the signal
        result = process_signal(data)
        
        # Send notification if needed
        if result['should_notify']:
            # Generate LLM message
            message = generate_recommendation_message(
                symbol=data.get('symbol'),
                price=data.get('price', 0),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {})
            )
            
            # Send Telegram notification
            send_trading_notification(
                symbol=data.get('symbol'),
                price=data.get('price', 0),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {}),
                secondary_message=message
            )
        
        return jsonify({
            'success': True,
            'signal_id': result['row_id'],
            'recommendation': result['recommendation'],
            'signal_strength': result['signal_strength'],
            'notified': result['should_notify']
        })
        
    except Exception as e:
        print(f"[Webhook 5m/30m/60m] Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/webhook/cross-alert-1h-4h-1d', methods=['POST'])
def webhook_1h_4h_1d():
    """
    Receive TradingView alert for 1h/4h/1d timeframes
    
    Expected data format:
    {
        "symbol": "TXF1!",
        "timeframe": "1H",
        "signal": "UP",
        "price": 32848,
        "kd": {
            "1h": { "k": 82.34, "d": 78.56, "dir": "多" },
            "4h": { "k": 65.12, "d": 60.45, "dir": "平" },
            "1d": { "k": 45.67, "d": 50.23, "dir": "空" }
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        required = ['symbol', 'kd']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Normalize timeframe keys (1h -> 60m, 4h -> 4h, 1d -> 1d)
        if 'kd' in data:
            kd = data['kd']
            if '1h' in kd and '60m' not in kd:
                kd['60m'] = kd.pop('1h')
            if '4h' not in kd and '4H' in kd:
                kd['4h'] = kd.pop('4H')
            if '1d' not in kd and '1D' in kd:
                kd['1d'] = kd.pop('1D')
        
        result = process_signal(data)
        
        if result['should_notify']:
            message = generate_recommendation_message(
                symbol=data.get('symbol'),
                price=data.get('price', 0),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {})
            )
            
            send_trading_notification(
                symbol=data.get('symbol'),
                price=data.get('price', 0),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {}),
                secondary_message=message
            )
        
        return jsonify({
            'success': True,
            'signal_id': result['row_id'],
            'recommendation': result['recommendation'],
            'signal_strength': result['signal_strength'],
            'notified': result['should_notify']
        })
        
    except Exception as e:
        print(f"[Webhook 1h/4h/1d] Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/webhook/cross-alert-all', methods=['POST'])
def webhook_all():
    """
    Receive complete TradingView alert with all timeframes
    
    Expected data format includes kd for 5m, 30m, 60m, 4h, 1d
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        required = ['symbol', 'kd']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        result = process_signal(data)
        
        if result['should_notify']:
            message = generate_recommendation_message(
                symbol=data.get('symbol'),
                price=data.get('price', 0),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {})
            )
            
            send_trading_notification(
                symbol=data.get('symbol'),
                price=data.get('price', 0),
                recommendation=result['recommendation'],
                signal_strength=result['signal_strength'],
                kd_data=data.get('kd', {}),
                secondary_message=message
            )
        
        return jsonify({
            'success': True,
            'signal_id': result['row_id'],
            'recommendation': result['recommendation'],
            'signal_strength': result['signal_strength'],
            'notified': result['should_notify']
        })
        
    except Exception as e:
        print(f"[Webhook All] Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=Config.DEBUG)
