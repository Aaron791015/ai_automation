# 投注機器人（wbot）壓測：前置檢查與執行

> 工具 `tools/wbot_Performance/`（聊天室 SignalR 併發下注；Flask 控制台 **:5100**）。
> 2026-08-17 自 `C:\GitLab\AutomationTest\webet_chatbot` 轉入，來源 repo 唯讀未改。
> 相依已裝進工作區 `.venv`（與七星那套不同，七星要用系統 Python）。
> 共通紀律（授權、對外用語、收尾回寫）見 `perf-test` SKILL.md §4／§6。

---

## 0. 環境

| 入口 | 指令 |
| --- | --- |
| CLI | `..\..\.venv\Scripts\python.exe scripts\run_perf.py ...`（cwd＝`tools\wbot_Performance`） |
| Web 控制台 | `web_ui\run_server.bat` → http://127.0.0.1:5100 |

產物在 `logs/runs/<run_id>/`。

---

## 1. 前置檢查（逐項打勾）

| # | 檢查 | 不通過時 |
| --- | --- | --- |
| **1** ⭐ | **主投後台網址是新的** —— 子網域是**亂數、由總控動態生成，站台一重建就變** | 到總控後台（`config` 的 `Environment.control_url`）的「主投列表」，把該主投的「後:」欄複製到 `config/wbot_perf_config.json` 的 `Environment.master_url`。<br>**這是每次跑壓測最常錯的一步** |
| 2 | 主投後台「网站设置」**已綁定 l5 前台會員** | 未綁定則聊天室顯示「**服务未启用**」，會員完全連不進去。QAT 用 `nett06` @ `l5_f.qat.st` |
| 3 | 足量測試會員 | 暱稱需含 `player_key`（預設「自動測試」）、餘額充足、**聊天室密碼一致且為 6 位數字**。<br>不足時 `--create-player`／`--update-player` 一次備妥 |
| 4 | **避開 05:00–08:00** | 那三小時不開盤、期號 061–096 不存在。排長跑要避開，否則中間三小時完全沒有下注 |
| 5 | 該站台此刻沒有別人在驗報表或對帳 | 下注＝真金流 |

---

## 2. 三個會讓數據靜默失真的時序陷阱

| # | 陷阱 |
| --- | --- |
| 1 | **`N连` 文本一次送出 ＝ N 期的注單**（回單標 `[ 连1/3 ]`）。<br>**送出訊息數 ≠ 注單數**；`退{编号}` 只退當期那筆，要 `停{编号}` 才停整個系列。<br>→ 冒煙／對帳敏感時用 `smoke` profile（單條非連投、下注後立即全退） |
| 2 | **退碼有時效** —— 必須在同一期**仍開盤**時送出，封盤後回 `超时退单失败` |
| 3 | **「完整期」不含頭尾** —— 第一期是中途加入、最後一期是停止時仍在進行的，<br>`period_summary.csv` 會標 `partial=true`。所以 `--max-periods 1` 實際會經過 **3 個期號** |

---

## 3. 執行範例

```powershell
cd tools\wbot_Performance

# 冒煙：3 會員、跑滿 1 個完整期、下注後立即退碼（不留殘留）
..\..\.venv\Scripts\python.exe scripts\run_perf.py --players 3 --profile smoke --stop-mode periods --max-periods 1

# 正式：1 主投 × 100 會員，跑 30 分鐘
..\..\.venv\Scripts\python.exe scripts\run_perf.py --players 100 --run-time 30m
```

⛔ **停止一律殺整棵程序樹** —— 孫程序握著 WebSocket，普通 terminate 殺不掉，**會繼續下注**。

---

## 4. 判讀

**先看報告首頁的「本輪數據可不可信」**：
`ws_write` 偏高 ＝ 壓測機自己飽和；分片沒到齊 ＝ 統計少算。

完整協定契約（精確配對鏈、`BotMessageType`、`PlayerBetHistoryType`）在
`docs/投注機器人/UI元素對照_投注聊天室.md` §「SignalR frame 層契約」。

---

## 5. 收尾

**還原與否由執行者於整批測試完成後決定**（判準與登記格式見 `perf-test` SKILL.md §6 第 1 條）。
狀態與待辦寫進 **`docs/投注機器人/wbot_Performance_效能驗證交接.md`**
（與功能線那份 `wbot_驗證交接.md` **互不重疊**）。
