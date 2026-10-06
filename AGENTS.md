# AGENTS.md — TradingSys

> 給 AI 看的專案筆記。**進入這個 topic 時會自動載入**,目的是讓對話 context 自動切到這個專案,不會跟其他專案混。

## 這是什麼

**TradingView 訊號接收 + KD 指標分析 + Telegram 推播**的 Flask webhook 服務。
對外網域 `trading.thetainformation.com`,接收 TradingView alert,分析 K/D 黃金交叉 / 死亡交叉,組合 1H/4H/1D 三個時框並用 1H 均線排列加權,給出「建議 / 積極 / 強烈 / 持續」的交易訊號,透過 LLM(OpenRouter)生成自然語言建議,推到 Telegram。

**訊號來源是 TradingView Pine 指標 `KDJ_MTF_1H_4H_1D`,送出的是純數值陣列(沒有欄位名稱、沒有商品代號)。**

## 路徑

- **專案根目錄**(本機):`/home/puremars/TradingSys`(原本是 `C:\Users\purem\OneDrive\文件\TradingSys`)
- **Flask app**:`./app/`(`app.py`、`config.py`、`models.py`、`services/`、`templates/`、`data/`)
- **Telegram 訂閱機制**:`./app/telegram_polling.py`(Long-poll 副 bot)、`./app/telegram_subscribers.py`(訂閱者 DB)(git 未追蹤)
- **SQLite DB**:在 `./app/data/`(用 volume 掛進容器做持久化)
- **對外網域**:`trading.thetainformation.com`

## 雙 Telegram Bot 架構

用 **兩個** 獨立的 Telegram bot(各一組 token+user_id):

| Bot | 變數 | 用途 |
|-----|------|------|
| 主 bot | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_USER_ID` | 推**完整**訊號(含 KD 明細 + LLM 建議),HTML parse_mode |
| 副 bot | `TELEGRAM_BOT_TOKEN_2` + `TELEGRAM_USER_ID_2` | 廣播**精簡測試訊號**(無 KD 明細 + 測試警告)給**所有訂閱者**;HTML 內容先 `html.escape` 跳脫再送 |

副 bot 是**訂閱制**:使用者對副 bot 發 `/start` 訂閱、`/stop` 退訂(見 `telegram_polling.py` / `telegram_subscribers.py`,git 未追蹤)。訂閱者存在 SQLite `telegram_subscribers` 表(`chat_id` 為主鍵)。所有推播都加前綴 `[此為測試功能,不可用於實際投資]`。

## 服務 / Port

| 服務 | 容器名 | 對外 Port | 內部 |
|------|--------|----------|------|
| Nginx | `nginx-tradingsys` | **8081** | 80 |
| Flask | `flask-tradingsys` | - | 5000 |
| cloudflared | `cloudflared-tradingsys` | - | - |

## Webhook 端點

| 路徑 | 方法 | 說明 |
|------|------|------|
| `/webhook/kd-sma` | POST | 唯一的訊號端點,吃數值陣列 |
| `/line-webhook` | POST | LINE Bot |
| `/api/status` | GET | 健康檢查 |
| `/foreign-futures` | GET | 外資期貨留倉(多單/空單/淨額)折線圖 |
| `/api/foreign-futures` | GET | 外資期貨留倉資料 JSON(`?days=N`) |
| `/` | GET | 狀態頁 |

Payload 格式(裸陣列,也接受 `{"values":[...]}`):

```
[SMA10, SMA60, SMA120, SMA720, K1H, D1H, K4H, D4H, K1D, D1D, PRICE]
```

- 四條 SMA 都是 **1H 週期**;第 11 個 PRICE 可省略
- 沒有商品代號 → 固定用 `Config.DEFAULT_SYMBOL`(`.env` 的 `DEFAULT_SYMBOL`,預設 `TXF1!`),可用 `?symbol=XXX` 覆寫
- 沒有 `signal` 欄位 → **交叉一律靠跟資料庫上一筆比對推導**

## 訊號判斷邏輯(在 `app/services/signal_analyzer.py`)

KD 部分(做空對稱):

| 條件 | 建議 | 強度 | 預計持續 |
|------|------|------|----------|
| 1D 黃金交叉 | 做多 | 強烈 | 數日-數週 |
| 4H 黃金交叉 + 1D 偏多 | 做多 | 強烈 | 數日-數週 |
| 4H 黃金交叉 | 做多 | 積極 | 1-數日 |
| 1H 黃金交叉 + 4H 偏多 + 1D 偏多 | 做多 | 積極 | 1-數日 |
| 1H 黃金交叉 + 4H 偏多 | 做多 | 建議 | 4-8 小時 |
| 1H 黃金交叉但 4H 偏空 | 無 | 無 | 逆勢,不推播 |
| 無交叉但 2 個以上週期同向 | 持有 | 持續 | - |

SMA 加權(**只調整強度,不單獨產生買賣建議**):

- 多頭排列 `10>60>120>720`:做多升一級、做空降一級
- 空頭排列 `10<60<120<720`:做空升一級、做多降一級
- 糾結:不調整;降到「無」就不推播

## 常用指令

```bash
# 啟動整組
docker compose up -d --build

# 看 webhook 收到的內容(debug 用)
docker compose logs -f flask

# 本機直接跑 Flask(不過 tunnel,測 webhook 方便)
pip install -r requirements.txt
cp .env.example .env  # 編輯填入 API key
python -m flask run --host=0.0.0.0 --port=5000

# 模擬 TradingView 推 webhook
curl -X POST http://localhost:8081/webhook/kd-sma \
  -H "Content-Type: application/json" \
  -d '[23000.5,22800,22500,21000,65.4,60.1,55.2,50.8,45.3,48.9,23050]'
```

## 環境變數(都在 `.env`)

| 變數 | 用途 |
|------|------|
| `DEFAULT_SYMBOL` | 商品代號,payload 不帶所以固定在這(預設 `TXF1!`) |
| `TELEGRAM_BOT_TOKEN` | 主 bot token(推完整訊號) |
| `TELEGRAM_USER_ID` | 主 bot 接收者 user id(目前是 `732924840`) |
| `TELEGRAM_BOT_TOKEN_2` | 副 bot token(訂閱制測試訊號,可留空 = 停用副 bot) |
| `TELEGRAM_USER_ID_2` | 副 bot 的固定接收者(遷移時自動加入訂閱表) |
| `OPENROUTER_API_KEY` | LLM API key |
| `OPENROUTER_MODEL` | 預設 `minimax/MiniMax-M2.7`(OpenRouter) |
| `CLOUDFLARE_TUNNEL_TOKEN` | 對外 tunnel token |
| `SECRET_KEY` | Flask session 簽章 |
| `FOREIGN_FUTURES_ENABLED` | 是否啟動外資期貨每日同步(預設 `true`) |
| `FOREIGN_FUTURES_COMMODITY` | 抓哪個期貨商品的外資留倉(預設 `TXF` 台指期) |

## 外資期貨留倉

- 抓取:`app/services/foreign_futures.py`,來源是期交所「三大法人 - 區分各期貨契約」CSV 下載端點 `futContractsDateDown`(Big5),只留「外資及陸資」那列的未平倉口數/金額
- 排程:`app/foreign_futures_scheduler.py` 背景執行緒。啟動先同步一次(DB 空的會往回補一年),之後平日台北時間 15:00–21:00 每 30 分鐘檢查,今天的資料進來就停
- 資料表:`foreign_futures_oi`(`trade_date` + `commodity` 為主鍵,重抓會覆寫)
- 手動補資料:`docker compose exec flask python -m app.services.foreign_futures --backfill 365`

## 已知的坑

- **WORKFLOW.md** 是這個專案的「規格書」,**最權威的業務邏輯來源**(比 README 詳細),有改動前先讀它
- SQLite 檔案在容器內是 `/app/app/data/`,靠 volume `./app/data:/app/app/data` 持久化;**不要用 `docker volume prune` 砍 volume**
- 訊號時間預估(4-8 小時 / 1-數日 / 數日-數週)是經驗值,不是技術指標
- **交叉靠「跟上一筆比對」推導**:因為 alert 只在交叉時才發,DB 裡相鄰兩筆可能隔好幾小時甚至數天。第一次部署後的第一筆資料沒有前一筆可比,不會有交叉訊號,屬正常
- 資料表還留著 `k_5m`/`k_30m` 等舊欄位給歷史資料,新訊號不寫入;`alert_group` 現在固定是 `swing`
- 1H 的 K/D 存在 `k_60m`/`d_60m` 欄位(同一組指標,只是舊命名)
- LLM 建議可能會被 OpenRouter rate limit,被擋時 Telegram 推播會延遲或失敗
- **去重**:相同(symbol、alert_group、recommendation、signal_strength)在 60 秒內出現會被視為重複,不推播(`has_recent_duplicate_notification`,response 的 `deduped` 欄位會是 `True`)
- 副 bot 的 `/start`、`/stop` 是透過 **Long-poll `getUpdates`** 收的(`telegram_polling.py`),不是 webhook,不受 cloudflared tunnel 影響
- 副 bot 的 HTML 內容在送到 Telegram 前會 `html.escape`(因為 AI 可能產出 `SMA10<60` 這類比較符,會讓 Telegram HTML parse 拒收)

## 相關文件

- `WORKFLOW.md` — 業務邏輯規格書(必讀)
- `README.md` — API 端點 + webhook payload 範例
- `docker-compose.yml` — 服務編排
- `requirements.txt` — Python 依賴
