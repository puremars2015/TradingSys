# TradingView Signal Bot

接收 TradingView 期貨KD指標數據,分析訊號強度,透過Telegram發送建議通知的系統。

## 功能

- 📊 接收 TradingView Webhook 數值陣列
- 📈 KD指標分析 (1H/4H/1D) + SMA均線排列加權 (SMA10/60/120/720,皆為1H週期)
- 🤖 LLM自動生成交易建議 (OpenRouter MiniMax M2.7)
- 📱 Telegram即時推播通知
- 💾 SQLite資料持久化

## 架構

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   TradingView   │────▶│   nginx      │────▶│   Flask     │
│   (Webhook)     │     │   :8080      │     │   :5000     │
└─────────────────┘     └──────────────┘     └─────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │ cloudflared  │
                        │   (Tunnel)   │
                        └──────────────┘
```

## Webhook 端點

| 路徑 | 方法 | 說明 |
|------|------|------|
| `/webhook/kd-sma` | POST | 訊號端點,吃數值陣列 |
| `/line-webhook` | POST | LINE Bot |
| `/api/status` | GET | 健康檢查 |

### Payload 格式

裸的 JSON 陣列(也接受 `{"values":[...]}` 包法):

```json
[23000.50, 22800.00, 22500.00, 21000.00, 65.40, 60.10, 55.20, 50.80, 45.30, 48.90, 23050.00]
```

| # | 內容 | 說明 |
|---|------|------|
| 1-4 | SMA10 / SMA60 / SMA120 / SMA720 | 皆為 1H 週期 |
| 5-6 | K1H / D1H | 1小時 KD |
| 7-8 | K4H / D4H | 4小時 KD |
| 9-10 | K1D / D1D | 日線 KD |
| 11 | PRICE | 當下價格(可省略) |

商品代號不在 payload 裡,固定用 `.env` 的 `DEFAULT_SYMBOL`(預設 `TXF1!`),必要時可用 `?symbol=XXX` 覆寫。

## 訊號分析邏輯

KD 部分(做空對稱):

| 條件 | 建議 | 強度 | 預計持續 |
|------|------|------|----------|
| 1D 黃金交叉 | 做多 | 強烈 | 數日-數週 |
| 4H 黃金交叉 + 1D偏多 | 做多 | 強烈 | 數日-數週 |
| 4H 黃金交叉 | 做多 | 積極 | 1-數日 |
| 1H 黃金交叉 + 4H偏多 + 1D偏多 | 做多 | 積極 | 1-數日 |
| 1H 黃金交叉 + 4H偏多 | 做多 | 建議 | 4-8小時 |
| 1H 黃金交叉但 4H偏空 | 無 | 無 | 逆勢,不推播 |
| 無交叉但2個以上週期同向 | 持有 | 持續 | - |

SMA 加權(只調整強度,不單獨產生買賣建議):

- 多頭排列 `SMA10>60>120>720`:做多升一級、做空降一級
- 空頭排列 `SMA10<60<120<720`:做空升一級、做多降一級
- 糾結:不調整;降到「無」就不推播

## 本地測試

```bash
# 安裝依賴
pip install -r requirements.txt

# 複製環境變量
cp .env.example .env
# 編輯 .env 填入你的設定

# 啟動 Flask
python -m flask run --host=0.0.0.0 --port=5000

# 測試 webhook
curl -X POST http://localhost:5000/webhook/kd-sma \
  -H "Content-Type: application/json" \
  -d '[23000.5, 22800, 22500, 21000, 65.4, 60.1, 55.2, 50.8, 45.3, 48.9, 23050]'
```

## Docker 部署

```bash
# 啟動服務
docker-compose up --build -d

# 查看日誌
docker-compose logs -f

# 停止服務
docker-compose down
```

## 環境變量

| 變量 | 說明 | 預設值 |
|------|------|--------|
| `SECRET_KEY` | Flask Secret Key | dev-secret-key |
| `DEBUG` | Debug模式 | false |
| `DEFAULT_SYMBOL` | 商品代號(payload 不帶) | TXF1! |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | - |
| `TELEGRAM_USER_ID` | Telegram User ID | - |
| `OPENROUTER_API_KEY` | OpenRouter API Key | - |
| `OPENROUTER_MODEL` | LLM模型 | minimax/m2.7b |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel Token | - |

## 目錄結構

```
TradingSys/
├── app/
│   ├── __init__.py
│   ├── app.py              # Flask 主應用
│   ├── config.py           # 設定
│   ├── models.py           # SQLite 模型
│   ├── services/
│   │   ├── signal_analyzer.py   # 訊號分析
│   │   ├── telegram_bot.py      # Telegram 通知
│   │   └── llm_generator.py     # LLM 生成
│   ├── templates/
│   │   └── index.html      # 狀態頁面
│   └── data/               # SQLite 資料庫目錄
├── docker-compose.yml
├── Dockerfile
├── nginx.conf
├── .env
└── requirements.txt
```

## License

MIT
