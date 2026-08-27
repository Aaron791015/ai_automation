# config/ — 測試環境設定

集中放置測試環境資訊。Claude 會**優先來這裡**找環境資料。

## 檔案分工（重要：敏感與非敏感分離）

| 檔案 | 內容 | 版控 | Claude 可自由讀取 |
| --- | --- | --- | --- |
| `environments.md` | **非敏感**：環境清單、前台/後台 URL、API base、彩種↔gameId 對應、期號規則等 | ✅ 可版控 | ✅ 是 |
| `config.local.json` | **敏感**：測試帳密、API token、DB 連線字串、金鑰 | ❌ **不版控** | 需要時才讀 |
| `config.example.json` | `config.local.json` 的**範本**（用假值示範結構） | ✅ 可版控 | ✅ 是 |

## 使用方式

1. 把非敏感的環境資訊直接填進 `environments.md`（我測試時會參考）。
2. 敏感資訊複製 `config.example.json` → 另存為 `config.local.json` 再填真值。
3. `config.local.json`、`.env` 已列入 `.gitignore`，不會進版控。

## JIRA 唯讀串接（`jira` 區塊）

`environments.json` 的 `jira.base_url` 為公司內網 JIRA 站台（可版控）；**帳密屬個人憑證，填在 `config.local.json`**：

```json
{ "jira": { "username": "<JIRA 帳號>", "password": "<JIRA 密碼>" } }
```

- 該站台為 Jira **Server 8.6.1**，早於 PAT（8.14 才支援）→ 只能用帳號密碼 Basic Auth。
- 填好後以 `python tools\jira_qa\jira_api.py --check` 驗證；驗證流程見 `/jira-verify` skill。
- ⚠️ 連續認證失敗會觸發 CAPTCHA 鎖定，屆時**密碼正確也會 401**，需人工用瀏覽器登入解鎖。
- **要下載附件（截圖）才需要 `session_cookie`**：站台有 2FA 外掛，附件走 web 層不吃 Basic Auth，
  需貼上瀏覽器中已通過 2FA 的 `JSESSIONID`（F12 → Application → Cookies）。會過期，失效時重貼。
  只讀單子內容不需要此欄。

> ⚠️ 請勿把帳密/token 寫進 `environments.md` 或程式碼。真需要我用機密登入某環境時，再告訴我讀 `config.local.json`。
