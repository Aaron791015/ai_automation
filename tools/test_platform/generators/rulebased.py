"""規則式生成器：關鍵詞抽取 ＋ 從既有案例庫找結構最近的當範本。

★ 它的天花板要先講清楚（UI 上也會標示）：
    **只處理有先例的需求。** 產出是「既有已驗證程式碼的重組」——
    從既有案例裡挑結構最近的一條，沿用它的 fixture、marker、斷言樣式與 POM 呼叫骨架，
    再把具體值換掉。**全新玩法／新頁面它生不出來**，那是規則式的極限，M6 接 Claude 才解。
    所以每一條產出都帶 `confidence` 與「參考了哪一條」，UI 一律標「請務必檢視」。

作法（四步，全部是可解釋的）：
    ① 切句 —— 需求文字按條列符號／編號／句號切成候選行，過濾掉標題與空話
    ② 抽詞 —— 每行抽出「動作詞」與「對象詞」
    ③ 配範本 —— 用對象詞與產品在既有案例裡找分數最高的一條當結構範本
    ④ 產碼 —— 以範本的 fixture 與斷言形狀鋪一個骨架，POM 呼叫**只挑索引裡存在的方法**
"""
from __future__ import annotations

import re

from generators.base import CaseGenerator

# 動作詞 → 案例語氣。順序即優先序（越前面越具體）
_VERBS = [
    (("不應", "不得", "不可", "禁止", "不能"), "negative", "應被擋下"),
    (("新增", "建立", "建置", "開立"), "create", "應建立成功"),
    (("修改", "編輯", "更新", "調整", "設定"), "update", "應更新成功"),
    (("刪除", "移除", "停用"), "delete", "應刪除成功"),
    (("計算", "結算", "對獎", "派彩"), "calc", "計算結果應正確"),
    (("查詢", "搜尋", "篩選", "檢視", "查看", "顯示"), "read", "應正確顯示"),
    (("應該", "應顯示", "應為", "須", "必須", "應"), "assert", "應符合規格"),
]
_WRITE_VERBS = {"create", "update", "delete"}
_STOP = re.compile(r"^[\s\-*#>0-9.、）)\]】]+")
_TAIL = re.compile(r"[\s：:，,。；;]+$")
_NOISE_LINE = re.compile(r"^(需求|背景|說明|目的|備註|附註|範圍|前提)[:：]?\s*$")
_TOKEN = re.compile(r"[一-鿿]{2,}|[A-Za-z_][A-Za-z0-9_]{2,}")
_SKIP_TOKENS = {"應該", "必須", "可以", "測試", "案例", "需求", "如果", "以及", "並且"}


def _clean(line: str) -> str:
    return _TAIL.sub("", _STOP.sub("", line)).strip()


def _classify(text: str) -> tuple[str, str]:
    for keys, kind, expected in _VERBS:
        if any(k in text for k in keys):
            return kind, expected
    return "assert", "應符合規格"


_HEADING_TAIL = ("需求", "規格", "說明", "變更", "調整", "設置", "設定", "功能")


def _is_heading(line: str, all_lines: list[str]) -> bool:
    """把「賠率變動設置需求」這種標題行剔掉 —— 它不是一條可驗的案例。

    判準三個都要成立：
      ① 不是唯一一行（唯一一行時它本身就是需求，不能丟）
      ② 短，且以「…需求／規格／說明／設定」這類名詞收尾
      ③ **整行找不到任何動作詞或判準詞** —— 這條是關鍵：
         「新增一筆賠率變動設定」也以「設定」收尾，但它開頭就是動作詞「新增」，
         是實打實的一條案例。只看結尾會把它一起丟掉（2026-08-21 回歸測試抓到）。
    """
    if len(all_lines) <= 1 or len(line) > 20 or not line.endswith(_HEADING_TAIL):
        return False
    has_verb = any(k in line for keys, _kind, _exp in _VERBS for k in keys)
    return not has_verb and not any(k in line for k in ("應", "須", "不得", "不可", "要"))


def _tokens(text: str) -> list[str]:
    """抽出比對用的詞。

    ⚠️ 中文沒有詞界 —— 只取 `_TOKEN` 抓到的整段（如「批量新增時」）幾乎比不中任何東西，
    因為 POM 的 docstring 寫的是「批量新增」。所以中文段落**額外展開 2～4 字的 n-gram**，
    比對時等於做子字串匹配。英文識別字維持整段（camelCase 拆開反而失真）。
    """
    out, seen = [], set()
    for t in _TOKEN.findall(text):
        if t in _SKIP_TOKENS:
            continue
        cands = [t]
        if re.fullmatch(r"[一-鿿]+", t) and len(t) > 2:
            cands += [t[i:i + n] for n in (2, 3, 4) for i in range(len(t) - n + 1)]
        for c in cands:
            if c not in seen and c not in _SKIP_TOKENS:
                seen.add(c)
                out.append(c)
    return out


class RuleBasedGenerator(CaseGenerator):
    name = "rulebased"
    disclaimer = ("規則式生成：本清單是由「既有案例的結構」推導出來的，不是理解需求後寫出來的。"
                  "步驟與斷言一定要人工檢視、補上真正的判準；全新玩法或新頁面它生不出來。")

    # ---------------------------------------------------------------- ①②③
    def propose_cases(self, requirement: str, context: dict) -> list[dict]:
        product = context.get("product") or "crux"
        existing = context.get("existing_cases") or []
        pom = context.get("pom") or []
        lines = [c for c in (_clean(x) for x in (requirement or "").splitlines())
                 if len(c) >= 6 and not _NOISE_LINE.match(c)]
        if len(lines) <= 1 and requirement:          # 沒有條列時退回以句號切
            lines = [c for c in (_clean(x) for x in re.split(r"[。；\n]", requirement)) if len(c) >= 6]
        lines = [ln for ln in lines if not _is_heading(ln, lines)]

        out = []
        for i, line in enumerate(lines[:20], 1):
            kind, expected = _classify(line)
            toks = _tokens(line)
            tpl = self._best_template(toks, product, existing)
            hints = self._pom_hints(toks, pom)
            out.append({
                "id": f"C{i:02d}",
                "title": line[:70],
                "product": product,
                "surface": self._guess_surface(line, tpl),
                "kind": kind,
                "preconditions": self._preconditions(product, tpl),
                "steps": self._steps(line, kind, hints),
                "expected": f"{line[:50]}　→　{expected}",
                "markers": ["write_action"] if kind in _WRITE_VERBS else ["smoke"],
                "template_from": tpl,
                "pom_hints": hints,
                "confidence": "medium" if (tpl and hints) else "low",
                "note": "" if (tpl and hints) else "找不到夠近的既有案例或 POM 方法 —— 骨架會偏空，需要人補",
                "source_line": line,
            })
        return out

    def _best_template(self, toks: list[str], product: str, existing: list[dict]) -> dict | None:
        """在既有案例裡找標題重疊最多的一條 —— 它的 fixture 與斷言樣式就是要抄的結構。

        ⛔ **生成出來的骨架不可以再當範本**（`kind == "generated"`）。
           它們在 demo 模式也會被案例索引收進來，若不排除就會形成回饋迴路：
           第二次生成抄第一次的骨架、第三次抄第二次的 —— 抄到的是「待補判準」而不是
           真的驗證過的結構，產出品質會一代不如一代。範本必須是**人寫過、跑過**的案例。
           （2026-08-21 走查當場就撞到：C01 的範本指到它自己上一次的產出。）
        """
        best, score = None, 0
        for c in existing:
            if c.get("product") != product or c.get("kind") == "generated":
                continue
            hay = (c.get("title") or "") + " " + (c.get("nodeid") or "")
            s = sum(1 for t in toks if t in hay)
            if s > score:
                best, score = c, s
        if not best:
            return None
        return {"nodeid": best.get("nodeid"), "title": best.get("title"),
                "markers": best.get("markers") or [], "score": score}

    def _pom_hints(self, toks: list[str], pom: list[dict]) -> list[dict]:
        """挑出可能用得上的 POM 方法。⛔ 只從索引裡挑，不自由發明。"""
        scored = []
        for m in pom:
            hay = "{} {} {}".format(m.get("cls", ""), m.get("method", ""), m.get("doc", ""))
            s = sum(1 for t in toks if t in hay)
            if s:
                scored.append((s, m))
        scored.sort(key=lambda x: -x[0])
        return [m for _s, m in scored[:4]]

    def _guess_surface(self, line: str, tpl: dict | None) -> str:
        if any(k in line for k in ("前台", "會員端", "投注頁")):
            return "前台"
        if any(k in line for k in ("聊天室", "主投", "機器人")):
            return "聊天室"
        if tpl and "/frontend/" in (tpl.get("nodeid") or ""):
            return "前台"
        return "後台"

    def _preconditions(self, product: str, tpl: dict | None) -> list[str]:
        base = {"crux": ["已以總監帳號登入後台（fixture `backend_page`）"],
                "wbot": ["已完成階段0 前置建立（fixture `wbot_target`）"],
                "qixing": ["已以總監帳號登入對應彩種站台"]}.get(product, [])
        if tpl:
            base.append("結構參考既有案例：`{}`".format(tpl["nodeid"]))
        return base

    def _steps(self, line: str, kind: str, hints: list[dict]) -> list[str]:
        target = hints[0]["cls"] if hints else "⚠️ 待補：對應的 Page Object"
        steps = ["進入相關頁面（{}）".format(target)]
        if kind in _WRITE_VERBS:
            steps.append("執行操作：{}".format(line[:40]))
            steps.append("重新載入頁面，確認變更已持久化")
        else:
            steps.append("讀取畫面上的值：{}".format(line[:40]))
        steps.append("⚠️ 待補：實際的判準（期望值來自哪份規格）")
        return steps

    # ---------------------------------------------------------------- ③產碼
    def write_code(self, case: dict, context: dict) -> str:
        product = case.get("product") or "crux"
        fixture = {"crux": "backend_page", "wbot": "zk_page", "qixing": "page"}.get(product, "page")
        hints = case.get("pom_hints") or []
        feature = {"crux": "CRUX 總監後台", "wbot": "投注機器人", "qixing": "七星"}.get(product, product)
        tpl = case.get("template_from") or {}

        body = []
        for i, s in enumerate(case.get("steps") or [], 1):
            body.append("    # 步驟 {}：{}".format(i, s))
        if hints:
            m = hints[0]
            # 參數一律給佔位常數 —— 生成器不知道該傳什麼，直接寫變數名會是 NameError，
            # 而 NameError 會讓整支檔在 --collect-only 之後才炸，比一眼看得到的 TODO 難修。
            args = ", ".join('"⚠️{}"'.format(a.split("=")[0]) for a in (m.get("args") or []))
            body += ["",
                     "    po = {}({})".format(m["cls"], fixture),
                     "    # 可用的方法（掃自 {}，本檔只允許呼叫索引裡存在的）：".format(m["path"])]
            for h in hints:
                line = "    #   {}.{}({})".format(h["cls"], h["method"], ", ".join(h.get("args") or []))
                if h.get("doc"):
                    line += "　" + h["doc"]
                body.append(line)
            body += ["    actual = po.{}({})".format(m["method"], args),
                     "",
                     "    # ⚠️ 待補判準：{}".format(case.get("expected", "")),
                     '    assert actual is not None, "⚠️ 這是生成的骨架，請換成真正的判準"']
        else:
            body += ["",
                     '    pytest.skip("⚠️ 生成的骨架尚未補上實作 —— 找不到對應的 Page Object 方法")']

        imports = []
        mods: dict[str, set] = {}
        for h in hints:
            mods.setdefault(h["module"], set()).add(h["cls"])
        for mod, clss in sorted(mods.items()):
            imports.append("from {} import {}".format(mod, ", ".join(sorted(clss))))

        head = ["@allure.feature(\"{}\")".format(feature),
                "@allure.story(\"{}\")".format(case.get("surface", "後台")),
                "@allure.title(\"{}\")".format(_esc(case.get("title", "")))]
        head += ["@pytest.mark.{}".format(m) for m in (case.get("markers") or ["smoke"])]

        doc = ['    """{}'.format(_esc(case.get("title", ""))),
               "",
               "    期望：{}".format(_esc(case.get("expected", "")))]
        doc += ["    前置：{}".format(_esc(p)) for p in (case.get("preconditions") or [])]
        doc += ["    範本：{}".format(tpl.get("nodeid") or "（無，找不到夠近的既有案例）"),
                '    """']

        return "\n".join(imports + ["", ""] + head
                         + ["def {}({}):".format(_func_name(case), fixture)]
                         + doc + body + [""])

    def module_header(self, draft: dict) -> str:
        req = (draft.get("requirement") or "").strip().splitlines()
        bs = chr(92)
        return "\n".join([
            "# -*- coding: utf-8 -*-",
            '"""{}'.format(_esc(draft.get("title", "生成的測試案例"))),
            "",
            "用途：由測試助手的「需求 → 案例 → 實作」動線生成的骨架。",
            "      需求來源：{}".format(draft.get("source_ref") or "（直接貼上的文字）"),
            "      生成：{}　生成器：{}".format(
                draft.get("updated_at") or draft.get("created_at"), draft.get("generated_by") or "規則式"),
            "使用方式：scripts{}run_ui_tests.ps1 -Filter <關鍵字>".format(bs),
            "前置條件：",
            "    · ⚠️ **本檔是骨架，不是可信的測試** —— 每一條的判準都標了「待補」，",
            "      請逐條補上真正的期望值（並註明規格出處）後才納入回歸。",
            "    · 產碼只呼叫 core/pom_index.py 掃到的既有 Page Object 方法，不自由發明 API。",
            "",
            "需求原文（節錄）：",
            *["    {}".format(_esc(ln)) for ln in req[:12]],
            '"""',
            "import allure",
            "import pytest",
        ])


def _esc(s: str) -> str:
    """避免生成的字串把 docstring 或 decorator 的引號打斷。"""
    return str(s or "").replace('"', "＂").replace(chr(92), "／")


def _func_name(case: dict) -> str:
    """函式名要看得出測試對象＋情境＋預期（CLAUDE.md §3）。中文可用，pytest 支援。"""
    t = re.sub(r"[^\w一-鿿]+", "_", case.get("title") or "").strip("_")
    cid = str(case.get("id", "c")).lower()
    return "test_{}_{}".format(cid, t[:40]) if t else "test_{}".format(cid)
