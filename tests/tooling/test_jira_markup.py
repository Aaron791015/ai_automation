# -*- coding: utf-8 -*-
"""JIRA wiki 標記轉換，以及**三條路不可以再分岔**（2026-08-28）。

## 為什麼需要這一支

2026-08-26 依使用者裁示把 Bug 單正文改成 JIRA wiki 標記，但只做在
**平台落檔**那條路（`web_ui/api/bugs_file.py`）。`bug-report` skill 與
`scripts/pack_bug_report.py` 都沒跟上 —— 於是同一個工作區同時產出兩種格式的 Bug 單
（實測本地 90 張活躍單：`##` 節名 41 張、裸行 12 張）。

⛔ **而 `lint_bug_assets` 的 W8 還刻意同時容忍兩種寫法**（它的註解寫著「別名是實況」）
—— 也就是說，唯一該發現這件事的守門測試，被放寬去遷就舊實況了。
所以這件事**沒有任何機制會發現**，是使用者 2026-08-28 自己問出來的。

⭐ 這一支釘的就是那個缺口：轉換只准有一份，三條路都要用它。

使用方式：`pytest tests/tooling/test_jira_markup.py -q`
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")


def _m():
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    import jira_markup
    return jira_markup


class Test轉換規則:
    def test_粗體用單星號(self):
        assert _m().to_jira(u"這是 **重點** 好") == u"這是 *重點* 好"

    def test_圍欄變code而且裡面不轉粗體(self):
        u"""⭐ 程式碼裡的 `**` 是次方運算，跟著轉會把它改壞。

        ⚠️ **樣本要挑真的會被改壞的** —— 第一版寫 `x**2`（只有一組 `**`），
        粗體規則本來就不會命中，於是「圍欄內也套用轉換」這個突變**照樣是綠的**。
        現在用 `a**2 + b**2`（兩組）＋ 圍欄內一行表格分隔行，兩條規則都會踩到；
        圍欄外另放一張真表格，確認切割沒有切過頭。
        """
        body = u"a**2 + b**2\n| --- | --- |\n"
        got = _m().to_jira(u"| 欄 | 值 |\n| --- | --- |\n```\n" + body + u"```\n後")
        assert ("{code}\n" + body + "{code}") in got, u"圍欄內容被動了：%r" % got
        assert u"||欄||值||" in got, u"圍欄外的表格沒轉 —— 切割切過頭了：%r" % got

    def test_表格分隔行要刪掉並把表頭改成雙豎線(self):
        u"""⚠️ JIRA 的 `|` 本來就是表格語法，分隔行會渲染成一列破折號的儲存格。"""
        got = _m().to_jira(u"| 欄 | 值 |\n| --- | --- |\n| a | 1 |")
        assert got == u"||欄||值||\n| a | 1 |", got

    def test_分隔行不在表格後面就不要動它(self):
        u"""⛔ 不可以看到 `| --- |` 就刪 —— 它可能是別的東西（例如程式碼旁的說明）。"""
        got = _m().to_jira(u"一段話\n| --- | --- |")
        assert "| --- | --- |" in got, got

    def test_節名去掉井字號(self):
        assert _m().strip_headings(u"## Actual result\n內文") == u"Actual result\n內文"
        assert _m().strip_headings(u"## 【Test Environment】") == u"【Test Environment】"

    def test_不動自己加的節名(self):
        u"""⛔ `## 成因分析` 不在 JIRA 的格式裡 —— 拿掉井字號之後讀者分不出它是標題。"""
        assert _m().strip_headings(u"## 成因分析\n內文") == u"## 成因分析\n內文"

    def test_反引號不轉(self):
        u"""⚠️ 使用者沒點名，而且它原樣顯示仍然可讀 —— 不要自作主張多轉一種。"""
        assert "`GetBetSummaries`" in _m().to_jira(u"呼叫 `GetBetSummaries` 時")


class Test只准有一份:
    u"""★ 本節是這次事故的正解：**三條路共用同一份實作**。

    ⛔ 不要改成「比對三邊產出一樣」—— 那只證明此刻一致，
       下次有人在其中一邊補一條規則，另外兩邊照樣默默分岔。
       要釘的是「**它們用的是同一個函式**」。
    """

    def test_平台落檔用共用那份(self):
        u"""⚠️ 要**真的 import**，不能只讀原始碼字串。

        2026-08-28 第一版只做字串比對，於是我把 `sys.path.insert` 寫進模組層、
        卻沒有 `import sys` —— **模組整個 import 不起來**（37 條測試紅），
        而這一條照樣是綠的。看起來有效而其實抓不到的測試，比沒有更糟。
        """
        platform = os.path.join(ROOT, "tools", "test_platform")
        if platform not in sys.path:
            sys.path.insert(0, platform)
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        from web_ui.api import bugs_file
        import jira_markup
        assert bugs_file._to_jira is jira_markup.to_jira, (
            u"平台又自己寫了一份轉換")
        src = io.open(os.path.join(platform, "web_ui", "api", "bugs_file.py"),
                      encoding="utf-8").read()
        assert "_BOLD = re.compile" not in src, u"平台留著自己的轉換規則"

    def test_打包交付用共用那份(self):
        src = io.open(os.path.join(SCRIPTS, "pack_bug_report.py"),
                      encoding="utf-8").read()
        assert "from jira_markup import" in src, u"打包沒接上轉換"
        assert "strip_headings(to_jira(" in src, u"接了卻沒用"

    def test_skill講得出寫法而且指向同一份實作(self):
        u"""⛔ skill 是**人與終端機 session** 手寫時的依據 —— 它沒講，手寫的就會是舊格式。

        2026-08-27 的 `CRUX-124` 就是這樣：照 skill 重寫，於是又產出一張 `##` 格式的單。
        分岔不是歷史遺留，是現在進行式。
        """
        src = io.open(os.path.join(ROOT, ".claude", "skills", "bug-report", "SKILL.md"),
                      encoding="utf-8").read()
        for kw in (u"{code}", u"裸行", u"summary 欄", u"jira_markup"):
            assert kw in src, u"skill 沒講「%s」" % kw
        # ⛔ 模板本身不可以再出現帶冒號的節名（那正是舊寫法）
        assert u"Reproduce Steps：" not in src, u"模板還是舊的帶冒號寫法"


class Test打包:
    def test_預設轉jira_可用旗標關掉(self):
        u"""⭐ 預設轉：交付的下游就是 JIRA。
        ⛔ 但要留退路 —— 有時要交的是 markdown（貼 wiki、寄信）。
        """
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        import pack_bug_report as P
        md = u"---\nid: X\n---\n\n## Actual result\n\n**錯了**\n"
        assert u"Actual result\n" in P.strip_internal(md)
        assert u"*錯了*" in P.strip_internal(md) and u"**錯了**" not in P.strip_internal(md)
        # 關掉之後維持 markdown
        off = P.strip_internal(md, jira=False)
        assert u"## Actual result" in off and u"**錯了**" in off

    def test_frontmatter不進交付副本(self):
        u"""⚠️ frontmatter 是 YAML、是我方的狀態欄位，貼進 JIRA 只是噪音。"""
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        import pack_bug_report as P
        assert "id: X" not in P.strip_internal(u"---\nid: X\n---\n\n內文\n")
