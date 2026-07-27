# TradingView的通訊分析與資料收集站點bot系統

## 目的
本網站站點,主要提供API給TradingView的資料傳遞用

## 架構
架構,採用flask撰寫網站API端點,sqlite作為資料庫紀錄,然後用nginx做反向代理,再用cloudflare tunnel做通信
部屬使用docker跟docker compose的方式處理,sqlite要做持久化保存,
可以參考workerfriend這個專案的做法:(C:\Users\purem\OneDrive\文件\workerfriend)

## 端點
名稱:kd-sma
路徑:https://trading.thetainformation.com/webhook/kd-sma
http type:post
資料格式:純數值陣列(不含欄位名稱)
[SMA10, SMA60, SMA120, SMA720, K1H, D1H, K4H, D4H, K1D, D1D, PRICE]

範例:
[23000.50, 22800.00, 22500.00, 21000.00, 65.40, 60.10, 55.20, 50.80, 45.30, 48.90, 23050.00]

說明:
- 四條SMA都是1H週期(SMA720約等於30天)
- 第11個元素PRICE是當下收盤價,可省略(只送10個元素也能收)
- 陣列不帶商品代號,固定視為台指期(環境變數DEFAULT_SYMBOL,預設TXF1!)
  需要監控別的商品時,用 ?symbol=XXX 覆寫
- 陣列不帶方向,交叉一律靠「跟資料庫上一筆比對」推導

TradingView端觸發時機(指標KDJ_MTF_1H_4H_1D):
- 1H / 4H / 1D 的KD各自發生黃金交叉或死亡交叉
- SMA10/60/120/720 任兩條發生交叉(共6組配對)
- 同一根K棒有多個條件成立時,只發一次alert

## 後續處理
收到TradingView的資料之後,將資料寫入sqlite裡面
sqlite紀錄:
流水號,收到資料時間,標的,價格,SMA10,SMA60,SMA120,SMA720,1小時k值,1小時d值,4小時k值,4小時d值,1日k值,1日d值,建議,強度
(1H的K/D沿用舊的k_60m/d_60m欄位;舊的5m/30m欄位保留給歷史資料,新訊號不再寫入)

然後檢查當前狀況:

KD判斷(做空對稱):
1. 1D黃金交叉                      → 做多 / 強烈
2. 4H黃金交叉 + 1D偏多             → 做多 / 強烈
3. 4H黃金交叉                      → 做多 / 積極
4. 1H黃金交叉 + 4H偏多 + 1D偏多    → 做多 / 積極
5. 1H黃金交叉 + 4H偏多             → 做多 / 建議
6. 1H黃金交叉但4H偏空              → 逆勢,不建議進場(不推播)
7. 無交叉但2個以上週期同向         → 持有 / 持續

SMA加權(只調整強度,不單獨產生買賣建議):
- 均線多頭排列(SMA10>60>120>720):做多升一級,做空降一級
- 均線空頭排列(SMA10<60<120<720):做空升一級,做多降一級
- 均線糾結:不調整
- 降級到「無」就不推播(逆勢過濾)

通常,
1H交叉的信號,大約持續4~8小時
4H交叉的信號,大約可以持續1天~數日
1D交叉的信號,大約可以持續數日~數週


## 發送通知訊息
1. 根據後續處理結果,呼叫LLM產生建議訊息
2. 然後推送給有在telegram的名單內的人

## telegram
1. bot token:8505755301:AAHdjoMsV18SMBkA5IR0BPnwd7L7UWAEXxg
2. user id:732924840