# 自帶字型（latin 子集）

主題 `Starlight Telemetry` 指定的三支字型，取自 Google Fonts 的 **latin 子集**，
放進版控以確保**離線與每台機器一致**（使用者 2026-08-19 裁示）。

| 檔案 | 字體 | 角色 | 授權 |
| --- | --- | --- | --- |
| `Inter-var.woff2` | Inter（可變字型 100–900） | 正文、標籤、**所有數字**（開 `tnum`） | OFL-1.1（`OFL-Inter.txt`） |
| `Sora-600.woff2` | Sora SemiBold | 品牌、卡片標題、基座產品名 | OFL-1.1（`OFL-Sora.txt`） |
| `JetBrainsMono-400.woff2` | JetBrains Mono | run_id、nodeid、console、JSON | OFL-1.1（`OFL-JetBrainsMono.txt`） |

- **中文不自帶**：完整繁中字型 5MB＋，不划算 → fallback `"Noto Sans TC", "Microsoft JhengHei"`。
- Inter 三個字重原本各下載一次，經 md5 比對確認 Google 回的是**同一支可變字型**，
  故合併為單檔並在 `@font-face` 用 `font-weight: 100 900` 宣告，省下 94KB。
- 取得日期 2026-08-19；來源為 `fonts.googleapis.com/css2` 的 `/* latin */` 區塊。
