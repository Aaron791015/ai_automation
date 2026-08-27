---
name: test-double-must-not-be-lenient
description: 測試裡的假實作（fake／monkeypatch）只要比真的寬鬆，測試就會假通過 —— 假 save_meta 用 dict.update 合併，而真的是整份覆寫，於是「刪掉某個鍵」永遠測不到
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 896fee9b-235f-42fb-af4a-1e0536ad221f
  modified: 2026-08-26T09:54:06.137Z
---

**⛔ 假實作的語義要跟真的一樣嚴，寬鬆一格就會把 bug 藏起來。**

測試通過不代表程式對——只代表**它沒違反假實作的規則**。假的比真的寬鬆時，
那條測試就從「驗證」退化成「裝飾」，而且**沒有任何訊號告訴你**。

## 實際踩到的樣子（2026-08-26）

`tests/tooling/test_platform_session_compact.py` 要驗「接上新 session 之後要
`pop` 掉 `pending_seed`」。假磁碟是這樣寫的：

```python
monkeypatch.setattr(CH, "save_meta", lambda mm: disk.update(mm))   # ❌ 合併
```

而真的 `save_meta` 是 `write_json_atomic`——**整份覆寫**。
於是 `mm.pop("pending_seed")` 在假磁碟上**永遠不生效**（`update` 只加不刪），
那條測試等於什麼都沒驗。改成忠實版本才抓得到：

```python
def _save(mm):
    disk.clear(); disk.update(mm)                                   # ✅ 整份覆寫
```

## 最容易寫寬鬆的四種

| 真實行為 | 常見的偷懶假實作 | 被藏起來的 bug |
| --- | --- | --- |
| 整份覆寫（`write_json_atomic`） | `dict.update` 合併 | **刪除鍵**永遠測不到 |
| 會拋例外（磁碟滿、權限、逾時） | 永遠成功 | 錯誤處理路徑整條沒驗到 |
| 有長度／格式／範圍限制 | 照單全收 | 邊界與驗證邏輯沒驗到 |
| 非同步／有順序 | 同步立即回 | 競態與順序 bug 沒驗到 |

**Why**：假實作是**你自己寫的規格**，而你會不自覺地照著「程式現在的樣子」寫它——
於是測試只確認了「程式跟我的假設一致」，沒確認「程式跟真實環境一致」。
這比沒有測試更糟：**沒有測試你會保持警覺，假通過的測試會讓你放心**。

**How to apply**：

- 寫假實作前**先看真的那支怎麼做**（`write_json_atomic`？會不會拋？有沒有上限？），
  在假實作的 docstring 寫明「真的是 X，所以這裡也做 X」。
- ⭐ **驗收自己的測試**：把它套在**已知有 bug 的版本**上，確認它會紅。
  不會紅就是假實作太寬鬆——這一次就是這樣抓到的。
- 特別留意**刪除／失敗／邊界**這三類，它們最常被假實作抹平。
- 同一則的反面：[[bash-heredoc-backslash-trap]]（工具靜默做了跟你以為不同的事，
  而且 `assert` 通過、`print` 顯示成功）。
