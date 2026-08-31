# memory-seed 索引

`scripts/bootstrap_workspace.py` 會把下列每一行照抄進本機的 `MEMORY.md`
（只抄「該則 seed 真的被安裝了」的那幾行，已存在的不重複加）。

⚠️ 新增 seed 時**要在這裡補一行**，否則裝進去了卻不會出現在索引，
等於 memory 存在但不會被想起 —— 那正是 memory 這一層要解決的問題。

格式與 `MEMORY.md` 完全相同：`- [標題](檔名.md) — 一句話的鉤子`

- [語言慣例](lang-traditional-chinese.md) — 回覆/註解/文件一律繁體中文
- [API 與 UI 分工規則](api-vs-ui-rule.md) — API 僅限非被測行為的前置準備；被測行為一律走 UI
- [UI 測試任務指引](ui-test-task-guidelines.md) — 任務描述四要素；拆小、點名被測行為、先探索後實作
- [驗證任務兩階段順序](verification-two-phase-order.md) — 目標項全部驗完出報告，才回頭驗 side effect
- [覆寫型驗證前先查可還原性](restore-check-before-overwrite.md) — 存量資料可能在新驗證下無法重建，動了就回不去
- [功能入口用 API 反查](feature-entry-lookup-by-api-not-name.md) — 選單名稱對不上功能名稱，主張「沒有入口」前先拿端點反查頁面
- [舊 Bug 單不回填，用新單追蹤](jira-verify-no-backfill-old-tickets.md) — 重驗發現部分修復時開新單承接殘留，舊單維持原狀
- [多 session 版控紀律](uncommitted-files-ownership.md) — 共用 working tree 為何需要紀律（四個踩過的坑）
- [amend 競態教訓](git-amend-race-shared-worktree.md) — 共用 worktree 下 amend 前必查 HEAD 仍是自己的 commit
- [假實作不可比真的寬鬆](test-double-must-not-be-lenient.md) — fake/monkeypatch 寬鬆一格，測試就從驗證退化成裝飾且無訊號；驗收自己的測試
- [規則被自己的守門測試釘住](rule-frozen-by-its-own-guard-test.md) — 規則過期卻改不掉，多半是「改了會紅」；守門測試要釘性質不釘字面
- [heredoc 反斜線坑](bash-heredoc-backslash-trap.md) — 用 heredoc 跑 Python 改檔時 Windows 路徑的反斜線會被吃掉且靜默失敗
- [環境帳密政策](env-credentials-policy.md) — environments.md 可版控測試站帳密，不視為外洩
- [STG 需授權才可使用](stg-requires-authorization.md) — ⛔STG 已交客戶試用，預設走 QAT
- [Playwright MCP 設定](playwright-mcp-setup.md) — .mcp.json 釘 0.0.77（Node 18 上限）＋ --isolated 各 session 隔離
- [統一測試平台](test-platform.md) — tools/test_platform（:5300）；registry 宣告式接工具、各自 PC 跑各自實例
- [範本 --sync 快照工作區](template-sync-snapshots-worktree-not-head.md) — 會把別人未提交的檔一起帶進鏡像；被擋下來時先查那是誰的
