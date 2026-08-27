# -*- coding: utf-8 -*-
"""Claude 生成器：真的把需求讀懂之後寫案例（規則式的天花板之外那一半）。

## 為什麼需要這一支

`generators/__init__.py` 從一開始就寫著 `if name == "claude": from generators.claude
import ClaudeGenerator  # M6` —— **而這個檔不存在**。後果不是報錯而已：

  · `platform_config.json` 把 `generator` 設成 `claude` → 整條動線 D 當場 `ImportError`
  · 「撰寫案例」任務按鈕起的 session 產出**沒有任何東西接得住** ——
    它把案例清單寫在對話裡，而平台這一側只認得規則式生成器的輸出

也就是說平台有**兩個**產生案例的入口，而它們之間沒有橋。
（2026-08-23 用 CRUX 實跑範本時發現：session 交出 8 條品質很好的案例，然後就斷在那裡。）

## 與規則式的分工

| | 規則式 | 本檔 |
| --- | --- | --- |
| 做得到 | **有先例**的需求 —— 從既有案例找結構最近的一條來重組 | 讀懂需求本身，全新玩法／新頁面也生得出來 |
| 判準來源 | 既有程式碼的形狀 | 需求文字 ＋ 它讀得到的規格文件 |
| 成本 | 毫秒、離線 | 一次 API 呼叫，數十秒 |

⛔ **兩者都不是「可以直接送出」的東西** —— ②人工檢視那一格不因供應者而異。

## 三條硬約束（與規則式相同，不因為換了供應者就放寬）

1. **POM 方法只能從 `context["pom"]` 挑** —— 索引裡沒有的一律丟掉。
   生成器自由發明方法名的代價是 `AttributeError`，而那要跑起來才看得到。
2. **生成出來的骨架不可以再當範本** —— 範本必須是人寫過、跑過的案例。
   本檔給 Claude 的既有案例樣本已排除 `kind == "generated"`。
3. **不給它寫檔的能力** —— 產出只是 JSON，寫檔由 `core/case_writer` 做（且會跑
   `--collect-only` 驗證）。

使用方式：`POST /api/drafts/generate {"generator": "claude", ...}`，
或把 `platform_config.json` 的 `generator` 設成 `"claude"` 當預設。
"""
from __future__ import annotations

import json
import re

from core import claude_session
from generators.base import CaseGenerator

#: 一次生成最多幾條 —— 超過這個量人也檢視不完，而檢視是這條動線的必要一格
MAX_CASES = 20

#: 允許出現在 `markers` 的值。⚠️ 與 `pyproject.toml` 的 markers 宣告一致，
#: 亂寫的 marker 會讓 pytest 在 `--strict-markers` 下整支檔收集失敗。
_MARKERS = ("smoke", "write_action")

# ⚠️ 語言標籤要吃掉**任何一種** —— 只寫 `json` 的話，模型回 ```python 時
#    「python」這個字會變成程式碼的第一行（實測 NameError，2026-08-23）。
_FENCE = re.compile(r"```[A-Za-z0-9_+-]*[ 	]*\r?\n(.+?)```", re.S)


def _first_json_array(text: str):
    """從回覆裡挖出 JSON 陣列。

    ⚠️ **不可以只試 `json.loads(text)`** —— 模型幾乎一定會在前後加說明文字，
       而那會讓整次生成以「JSONDecodeError」收場，看起來像模型壞了。
    """
    for chunk in _FENCE.findall(text or ""):
        try:
            got = json.loads(chunk.strip())
            if isinstance(got, list):
                return got
        except ValueError:
            continue
    start = (text or "").find("[")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        got = json.loads(text[start:i + 1])
                        if isinstance(got, list):
                            return got
                    except ValueError:
                        break
        start = text.find("[", start + 1)
    return None


def _ask(prompt: str, *, model: str | None = None) -> str:
    """送一次、把 text 事件接成一段字串。

    ⚠️ 這裡**不需要**串流 —— 生成是一次性的請求／回應，串流只會讓呼叫端複雜化。
    """
    okay, why = claude_session.available()
    if not okay:
        raise RuntimeError(why)
    out, err = [], None
    for ev in claude_session.ask(prompt, model=model):
        if ev.get("type") == "text":
            out.append(ev.get("text") or "")
        elif ev.get("type") == "error":
            err = ev.get("message")
    if err and not out:
        raise RuntimeError(err)
    return "".join(out)


def _pom_catalog(pom: list[dict], limit: int = 120) -> str:
    """把 POM 索引壓成一份**可以照抄的清單**（這是產碼唯一允許用的方法）。"""
    rows = []
    for m in (pom or [])[:limit]:
        sig = "%s.%s(%s)" % (m.get("cls", ""), m.get("method", ""),
                            ", ".join(m.get("args") or []))
        doc = ("　" + m["doc"]) if m.get("doc") else ""
        rows.append("  %s  ← %s%s" % (sig, m.get("module", ""), doc))
    return "\n".join(rows) or "  （這個產品還沒有 Page Object）"


def _example_titles(existing: list[dict], product: str, limit: int = 12) -> str:
    """既有案例的標題樣本 —— 給它看**命名風格**，不是給它抄內容。

    ⛔ 排除 `kind == "generated"`：生成物再當範本會形成回饋迴路，
       抄到的是「待補判準」而不是驗證過的結構（規則式的同名護欄）。
    """
    rows = []
    for c in existing or []:
        if c.get("product") != product or c.get("kind") == "generated":
            continue
        if c.get("title"):
            rows.append("  · " + c["title"])
        if len(rows) >= limit:
            break
    return "\n".join(rows) or "  （這個產品還沒有既有案例）"


_CASE_KEYS = ("title", "surface", "kind", "preconditions", "steps",
              "expected", "markers", "confidence", "note")


class ClaudeGenerator(CaseGenerator):
    name = "claude"
    disclaimer = ("Claude 生成：它讀懂了需求才寫，但**判準的正確性仍要人確認** —— "
                  "尤其是「期望值來自哪份規格」這一欄，模型寫得出來不代表它查證過。"
                  "POM 方法已限制在索引內，索引外的呼叫會被丟掉。")

    # ------------------------------------------------------------------ ①
    def propose_cases(self, requirement: str, context: dict) -> list[dict]:
        product = context.get("product") or "crux"
        pom = context.get("pom") or []
        allowed = {"%s.%s" % (m.get("cls"), m.get("method")) for m in pom}

        prompt = _PROPOSE_PROMPT.format(
            product=product, max_cases=MAX_CASES,
            markers="／".join(_MARKERS),
            pom=_pom_catalog(pom),
            examples=_example_titles(context.get("existing_cases") or [], product),
            requirement=(requirement or "").strip())

        raw = _ask(prompt)
        got = _first_json_array(raw)
        if got is None:
            raise RuntimeError(
                "Claude 沒有回出可解析的 JSON 陣列（回了 %d 字）。"
                "需求文字太短或太抽象時容易這樣 —— 試著改成條列，一條一件事。" % len(raw))

        out = []
        for i, c in enumerate(got[:MAX_CASES], 1):
            if not isinstance(c, dict) or not (c.get("title") or "").strip():
                continue
            hints = self._keep_real_pom(c.get("pom_hints"), pom, allowed)
            markers = [m for m in (c.get("markers") or []) if m in _MARKERS] or ["smoke"]
            out.append({
                "id": "C%02d" % i,
                "title": str(c.get("title"))[:70],
                "product": product,
                "surface": c.get("surface") or "後台",
                "kind": c.get("kind") or "assert",
                "preconditions": [str(x) for x in (c.get("preconditions") or [])],
                "steps": [str(x) for x in (c.get("steps") or [])],
                "expected": str(c.get("expected") or ""),
                "markers": markers,
                "template_from": None,          # ⚠️ 本供應者不抄既有案例的結構
                "pom_hints": hints,
                "confidence": c.get("confidence") if c.get("confidence") in (
                    "high", "medium", "low") else ("medium" if hints else "low"),
                "note": self._note(c, hints),
                "source_line": str(c.get("source_line") or c.get("title") or "")[:120],
            })
        if not out:
            raise RuntimeError("Claude 回的陣列裡沒有一條有標題 —— 需求可能不是可測的敘述")
        return out

    @staticmethod
    def _keep_real_pom(raw, pom: list[dict], allowed: set) -> list[dict]:
        """⛔ 只留索引裡真的存在的方法 —— 模型發明的方法名一律丟掉。

        丟掉而不是報錯：少一個 hint 只是骨架偏空（人補得回來），
        而放行一個不存在的方法會變成 `AttributeError`，要跑起來才看得到。
        """
        keep, seen = [], set()
        for item in raw or []:
            if isinstance(item, dict):
                key = "%s.%s" % (item.get("cls"), item.get("method"))
            elif isinstance(item, str):
                key = item.strip()
            else:
                continue
            if key in allowed and key not in seen:
                seen.add(key)
                cls, method = key.split(".", 1)
                keep.append(next(m for m in pom
                                 if m.get("cls") == cls and m.get("method") == method))
        return keep[:4]

    @staticmethod
    def _note(c: dict, hints: list[dict]) -> str:
        bits = []
        if c.get("note"):
            bits.append(str(c["note"]))
        if not hints:
            bits.append("找不到對應的 POM 方法 —— 骨架會偏空，需要人補")
        if not (c.get("expected") or "").strip():
            bits.append("⚠️ 沒有寫出期望值")
        return "；".join(bits)

    # ------------------------------------------------------------------ ③
    def write_code(self, case: dict, context: dict) -> str:
        product = case.get("product") or "crux"
        pom = context.get("pom") or []
        hints = case.get("pom_hints") or []
        fixture = {"crux": "backend_page", "wbot": "zk_page",
                   "qixing": "page"}.get(product, "page")
        feature = {"crux": "CRUX 總監後台", "wbot": "投注機器人",
                   "qixing": "七星"}.get(product, product)

        prompt = _CODE_PROMPT.format(
            feature=feature, surface=case.get("surface") or "後台",
            fixture=fixture,
            markers="\n".join("@pytest.mark.%s" % m for m in (case.get("markers") or ["smoke"])),
            title=case.get("title", ""),
            expected=case.get("expected", ""),
            preconditions="\n".join("  · " + p for p in (case.get("preconditions") or [])) or "  （無）",
            steps="\n".join("  %d. %s" % (i, s) for i, s in enumerate(case.get("steps") or [], 1)) or "  （無）",
            pom=_pom_catalog(hints or pom, limit=30))

        code = _strip_fence(_ask(prompt))
        if "def test_" not in code:
            # 產不出來就退回一個**看得出來是骨架**的東西，而不是塞一段跑不動的碼
            return _fallback_code(case, fixture, feature)
        return code.rstrip() + "\n"

    def module_header(self, draft: dict) -> str:
        return (
            '"""{title}\n\n'
            "本檔由測試助手的 **Claude 生成器**產出（需求 → 案例 → 產碼 → 寫檔）。\n"
            "⚠️ **這是骨架，不是驗證過的案例** —— 判準（期望值來自哪份規格）必須人工確認。\n\n"
            "來源需求：{source}\n"
            "使用方式：`pytest {path} -v`\n"
            '"""\n'
        ).format(title=draft.get("title") or "生成的測試案例",
                 source=draft.get("source_ref") or "（平台的需求貼上）",
                 path="tests/%s/" % (draft.get("product") or ""))


def _strip_fence(text: str) -> str:
    got = _FENCE.findall(text or "")
    if got:
        return got[0].strip()
    return (text or "").strip()


def _fallback_code(case: dict, fixture: str, feature: str) -> str:
    """產碼失敗時的骨架 —— **一定要 skip**，不能留一條假的綠燈。"""
    title = (case.get("title") or "").replace('"', "'")
    return (
        '@allure.feature("%s")\n'
        '@allure.title("%s")\n'
        "@pytest.mark.smoke\n"
        "def test_待補(%s):\n"
        '    """%s\n\n'
        "    期望：%s\n"
        '    """\n'
        '    pytest.skip("⚠️ 生成器沒能產出這一條的實作 —— 請人工補上")\n'
    ) % (feature, title, fixture, title, (case.get("expected") or "").replace('"', "'"))


_PROPOSE_PROMPT = """你正在替一個彩票測試工作區把需求拆成測試案例。產品代號：{product}。

## 只回 JSON

回一個 JSON 陣列，**不要任何其他文字**，最多 {max_cases} 條。每個元素：

```
{{
  "title":         "一句話講這條在驗什麼（測試對象＋情境＋預期結果）",
  "surface":       "後台" | "前台" | "聊天室",
  "kind":          "read" | "create" | "update" | "delete" | "calc" | "negative" | "assert",
  "preconditions": ["前置條件"],
  "steps":         ["步驟"],
  "expected":      "期望值，**要寫出依據哪份規格／公式**",
  "markers":       ["{markers} 之一或多個"],
  "pom_hints":     ["Class.method"],
  "confidence":    "high" | "medium" | "low",
  "note":          "你不確定的地方（沒有就空字串）"
}}
```

## 硬規則

1. **被測行為一律走 UI**，API 只能用在前置資料準備（這個工作區的 CLAUDE.md §5）。
2. `pom_hints` **只能從下面這份清單挑**，發明的方法名會被丟掉：

{pom}

3. 寫入型（下注／建帳號／改設定）用 `write_action`，唯讀用 `smoke`。
4. `expected` 沒有依據就在 `note` 說明「判準待確認」，⛔ **不要編一個規格出來**。
5. 一條案例只驗一件事。分不清就拆成兩條。

## 既有案例的命名風格（給你看語氣，不是要你抄內容）

{examples}

## 需求

{requirement}
"""


_CODE_PROMPT = """把下面這條測試案例寫成**一個** pytest 測試函式。只回程式碼，不要說明。

## 規格

- 功能：{feature}　介面：{surface}
- fixture 用 `{fixture}`
- 裝飾器依序：`@allure.feature` / `@allure.story` / `@allure.title`，然後：
{markers}
- 函式要有**繁體中文 docstring**，寫明期望與前置
- ⛔ **只能呼叫下面清單裡的 POM 方法**，不存在的方法一律不要用；
  參數不確定時給字面常數佔位並在旁邊註解，⛔ 不要用未定義的變數（那是 NameError）
- 判準不確定時寫 `pytest.skip("⚠️ ...")`，⛔ **不要寫一個必然通過的斷言**

## 可用的 POM 方法

{pom}

## 案例

標題：{title}
期望：{expected}
前置：
{preconditions}
步驟：
{steps}
"""
