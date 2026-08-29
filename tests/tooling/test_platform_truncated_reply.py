# -*- coding: utf-8 -*-
"""這一輪沒有 `done` 事件時，平台要**撿回結尾並講出來**（2026-08-27）。

為什麼需要這一支
    使用者回報「非任務對話沒有回應任何結果」。查證 session `29bc6a46`：
      · claude **寫出了完整的中文結論**（transcript 09:21:40.967Z）
      · 平台落檔的訊息卻只有工具之間的四句英文旁白，`usage` 是 `null`
        —— `null` ＝ `meta` 空的 ＝ **整輪沒收到 `done` 事件**
      · Flask 行程 17:10 起沒重啟過，所以不是平台掛掉
    也就是「答案產出了，只是沒走到平台這一側」，而平台**完全沒有反應**：
    `claude_session.ask()` 只在「exit code 非 0 **且** stderr 有東西」時才報錯，
    乾淨退出卻沒有 result、以及 client 斷線，兩種都是靜默的。

    ⛔ 這種靜默最貴：使用者看到最後一句旁白就沒有下文，
    完全看不出「它其實做完了」還是「它死了」—— 兩者的下一步完全不同。

使用方式：`pytest tests/tooling/test_platform_truncated_reply.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _platform():
    """⛔ **模組層絕對不可以做這件事**（`test_collect_all_roots.py` 專門守它）。

    把 `tools/test_platform` 插到 `sys.path` 最前面之後，`tests/wbot/perf` 的
    `from core.time_utils import …` 會找到**平台的 `core`** —— 兩個目錄一起收集
    就整包炸掉，而分開跑各自都是綠的。2026-08-27 本檔第一版就是這樣寫的，
    被那支測試當場抓到。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)


def _rows(tmp_path, entries):
    """寫一份假的 claude transcript（只放本測試在意的欄位）。"""
    p = tmp_path / "cid.jsonl"
    with io.open(str(p), "w", encoding="utf-8", newline="\n") as f:
        for ts, blocks in entries:
            f.write(json.dumps({
                "type": "assistant", "timestamp": ts,
                "message": {"content": blocks},
            }, ensure_ascii=False) + "\n")
    return str(p)


class Test撿回結尾:
    def test_只撿指定時間之後的段落(self, tmp_path, monkeypatch):
        u"""⚠️ 同一個 cid 累積了**這個 session 的每一輪** ——
        不過濾就會把上一輪的結論當成這一輪的補回來，那比沒補更糟。"""
        _platform()
        from core import transcript
        p = _rows(tmp_path, [
            ("2026-08-27T09:00:00.000Z", [{"type": "text", "text": u"上一輪的結論"}]),
            ("2026-08-27T09:21:40.967Z", [{"type": "text", "text": u"這一輪的結論"}]),
        ])
        monkeypatch.setattr(transcript, "path_for", lambda cid: p)
        got = transcript.texts_since("cid", "2026-08-27T09:14:00")
        assert got == [u"這一輪的結論"], u"時間過濾沒生效：%s" % got

    def test_不可以把thinking當成答覆(self, tmp_path, monkeypatch):
        u"""⛔ `thinking` 是推論過程，不是給人的答覆 —— 撿進來會把內心話貼到對話裡。"""
        _platform()
        from core import transcript
        p = _rows(tmp_path, [
            ("2026-08-27T09:21:00.000Z", [{"type": "thinking", "thinking": u"內心話"},
                                          {"type": "text", "text": u"正式回覆"}]),
        ])
        monkeypatch.setattr(transcript, "path_for", lambda cid: p)
        assert transcript.texts_since("cid", "2026-08-27T09:00:00") == [u"正式回覆"]

    def test_讀不到一律回空不可以拋(self, monkeypatch):
        u"""⛔ 這是**補救**路徑 —— 它自己壞掉不可以再把主流程弄倒。"""
        _platform()
        from core import transcript
        monkeypatch.setattr(transcript, "path_for", lambda cid: None)
        assert transcript.texts_since("cid", "2026-08-27T09:00:00") == []
        assert transcript.texts_since("", "") == []


class Test講出來:
    def test_沒有done就要補救並講明白(self, monkeypatch):
        u"""★ 核心迴歸：**已經收到的旁白要留著**，補回來的接在後面，再加一句警語。

        ⛔ 不可以把已收到的內容丟掉換成錯誤訊息 —— 逾時那條路的註解記過同一件事：
        「跑了幾十分鐘的產出丟掉等於那段時間白花」。
        """
        _platform()
        from web_ui.api import chat
        monkeypatch.setattr(chat, "get_meta", lambda sid: {"claude_session_id": "cid"})
        monkeypatch.setattr(chat.transcript, "texts_since",
                            lambda cid, since: [u"旁白一", u"漏掉的結論"])
        lost, note = chat._recover_truncated("sid", [u"旁白一"], "2026-08-27T09:00:00")
        assert lost == [u"漏掉的結論"], u"沒去重 —— 已經顯示過的旁白會再出現一次"
        assert u"沒有收到結束訊號" in note, u"沒講出這一輪不正常"
        assert u"補回來" in note, u"補了卻沒說，人會以為它本來就有講"
        # ⭐ 一定要給下一步 —— 只說「壞了」等於把人留在死路上
        assert u"再送一則訊息" in note and u"完整脈絡" in note

    def test_撿不到東西也要講(self, monkeypatch):
        u"""⛔ 撿不到就沉默 ＝ 回到 bug 本身。要講明「上面就是全部」。"""
        _platform()
        from web_ui.api import chat
        monkeypatch.setattr(chat, "get_meta", lambda sid: {"claude_session_id": "cid"})
        monkeypatch.setattr(chat.transcript, "texts_since", lambda cid, since: [])
        lost, note = chat._recover_truncated("sid", [u"旁白"], "2026-08-27T09:00:00")
        assert not lost
        assert u"沒有收到結束訊號" in note and u"就是中止前產出的全部" in note

    def test_時間基準要往前留餘裕(self):
        u"""⚠️ 兩邊的時鐘不保證同步，抓太緊會把這一輪最前面的段落濾掉。"""
        import datetime as dt

        _platform()
        from web_ui.api import chat
        now = dt.datetime.now(dt.timezone.utc)
        got = dt.datetime.strptime(chat._utc_now(), "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc)
        gap = (now - got).total_seconds()
        assert 3 <= gap <= 15, u"餘裕是 %s 秒 —— 太緊會濾掉開頭，太鬆會撈到上一輪" % gap


class Test落檔:
    def test_警語要進落檔的訊息不是只送SSE(self):
        u"""⛔ 只送 SSE 的話，等一下重開這個 session 看到的是一段沒頭沒尾的內容，
        而且**看起來像它正常講完的** —— 那正是使用者這次遇到的形狀。"""
        src = io.open(os.path.join(PLATFORM, "web_ui", "api", "chat.py"),
                      encoding="utf-8").read()
        i = src.index("def _persist_turn(sid, m, st):")
        seg = src[i:i + 2500]
        assert "_recover_truncated" in seg, u"SSE 這條路沒有補救"
        assert "reply = reply +" in seg, u"警語沒有寫進落檔的 reply"
        assert seg.index("reply = reply +") < seg.index("append_message"), (
            u"警語加在 append_message 之後 ＝ 沒存到")

    def test_補救要放在persist裡不是迴圈後面(self):
        u"""⚠️ client 斷線時 generator 收到 `GeneratorExit`，**迴圈後面永遠跑不到** ——
        而斷線正是最需要補救的情境。`_persist()` 是唯一在 `finally` 也會跑到的漏斗。
        """
        src = io.open(os.path.join(PLATFORM, "web_ui", "api", "chat.py"),
                      encoding="utf-8").read()
        i = src.index("def _turn_events(")
        body = src[i:src.index("def _persist_turn(")]
        assert "_recover_truncated" not in body, (
            u"補救寫在跑事件的迴圈後面 —— 那一輪被中止或斷線時不會執行")


def test_實例迴歸_29bc6a46那一輪撿得回結論():
    u"""★ 用**真的壞掉的那一輪**當樣本（2026-08-27，使用者回報的 session）。

    ⛔ 這條不可以改成假資料 —— 假資料證明不了「真的 transcript 長這樣也讀得出來」，
    而這次的 bug 正是「程式對得起規格、對不起現場」。

    ⚠️ **跳過的條件要問 `path_for()` 本人，不可以自己拼路徑** ——
    第一版寫死了 `~/.claude/projects/c--GitLab-Automation/…`，而 `path_for()`
    是依 `REPO_ROOT` 算 project key 的。於是在**範本鏡像**
    （project key 變成 `c--GitLab-QA-Template`）裡條件成立、卻一段都撿不到
    → 由「跳過」變成「失敗」，範本的三條自我驗收整個紅掉。
    ⭐ 這正是鏡像存在的價值：只在原型 repo 跑，這個缺陷看不見。
    """
    _platform()
    from core import transcript
    CID = "72a9e28a-5e26-4a28-979e-bab4d08c5b9e"
    if not transcript.path_for(CID):
        pytest.skip("這個 repo 讀不到那份 transcript —— 實例迴歸，不是必要條件")
    got = transcript.texts_since(CID, "2026-08-27T09:14:00")
    assert got, u"那一輪的內容一段都撿不回來"
    assert any(u"問題確認" in t for t in got), (
        u"撿回來的內容裡沒有那段中文結論 —— 補救對這個真實案例無效")


# ─────────────────────── review 補的三條（2026-08-27 自我 review）

def test_已經有錯誤訊息時不要再講一次原因():
    u"""⛔ 逾時那條路已經有一則講得很清楚的訊息（「已達本次的時間上限…」）。

    這時再接一句「串流在中途斷了（關掉分頁、重整…）」會**把原因說成別的事** ——
    人會去找自己是不是不小心關了分頁。這裡只補「撿回來了」，原因留給那一則自己講。
    """
    _platform()
    from web_ui.api import chat
    import types
    monkey = types.SimpleNamespace()
    orig_meta, orig_ts = chat.get_meta, chat.transcript.texts_since
    try:
        chat.get_meta = lambda sid: {"claude_session_id": "cid"}
        chat.transcript.texts_since = lambda cid, since: [u"中止前的最後一段"]
        lost, note = chat._recover_truncated("sid", [], "2026-08-27T09:00:00",
                                             had_error=True)
        assert lost == [u"中止前的最後一段"], u"有錯誤就不撿了 —— 那才是最該撿的一次"
        assert u"補回來" in note
        assert u"關掉分頁" not in note, u"又把原因說成別的事了"
        # 撿不到就完全不講 —— 錯誤訊息本身已經夠了，再加一句只是噪音
        chat.transcript.texts_since = lambda cid, since: []
        assert chat._recover_truncated("sid", [], "2026-08-27T09:00:00",
                                       had_error=True)[1] == ""
    finally:
        chat.get_meta, chat.transcript.texts_since = orig_meta, orig_ts
    del monkey


def test_逾時也要補救_兩條路要一致():
    u"""⛔ 第一版 POST 路徑寫成 `if not meta and not err` —— 有錯誤就跳過補救，
    而 SSE 路徑只看 `not meta` 照補。**同一件事兩條路行為不同**，
    而且跳過的那一側正是逾時（跑了幾十分鐘，最該把產出撿回來的一次）。
    """
    _platform()
    src = io.open(os.path.join(PLATFORM, "web_ui", "api", "chat.py"),
                  encoding="utf-8").read()
    assert "if not meta and not err:" not in src, (
        u"POST 路徑又跳過有錯誤的那一輪了")
    # ⚠️ 釘「**兩條路都會呼叫**」而不是釘參數怎麼寫 —— 2026-08-28 串流那條的
    #    起算時間改成放在 `st["t0"]` 裡（一輪一份），釘字面會誤報。
    assert src.count("_recover_truncated(") == 3, (
        u"兩條路都要補救（POST ＋ 串流），加上定義那一行共 3 處")


def test_被截斷要進結果確認():
    u"""★ 「結果確認」的價值就在**留得住**（關掉視窗、隔天再來都還在）——
    而截斷最常見的成因**正是關掉視窗**。不放進去，隔天回來只看得到半份產出，
    而且看不出它是半份。

    ⛔ 而且要排在最前面：它會改變下面每一條的可信度。
    """
    _platform()
    from web_ui.api.sessions import _output_summary
    out = _output_summary({"truncated": True,
                           "filed": [{"bug_id": "CRUX-999", "product": "CRUX"}]}, "sid")
    assert out and out[0]["kind"] == "warn", u"截斷警示沒有排在最前面：%s" % out
    assert u"沒有收到結束訊號" in out[0]["text"]
    assert u"接著剛才的繼續" in out[0]["text"], u"沒給下一步"
    # ⛔ 正常結束的那一輪不可以冒出這一列
    assert not [x for x in _output_summary({"filed": []}, "sid")
                if x.get("kind") == "warn" and u"結束訊號" in x.get("text", "")]
