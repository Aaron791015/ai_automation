# -*- coding: utf-8 -*-
"""邊界壓縮（`core/session_compact.py`）與 `--autocompact` 安全網。

用途：釘住「只在回覆邊界壓縮」這件事的三個要害 ——
      ① 該不該壓的判斷　② **壓縮失敗絕不能弄丟舊 session**　③ 種子要帶得動下一段。

⛔ 這裡最重要的不是「省多少」，是**失敗時的行為**：壓縮是加值，
   把任務弄死不是。所以失敗路徑的測試比happy path 還多。

前置條件：無（transcript 用臨時檔假造，不碰 ~/.claude）。
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _load(name):
    """⛔ **不可以在模組層動 `sys.path`** —— 會污染整場 pytest，

    把別的產品同名的 `core` 套件蓋掉（`test_platform_js_syntax` 有守門測試）。
    照本目錄既有慣例，延遲到函式裡再插。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import importlib
    return importlib.import_module(name)


@pytest.fixture
def C():
    return _load("core.session_compact")


def _usage_line(read=0, write=0, inp=0):
    return json.dumps({"message": {"id": "m1", "usage": {
        "input_tokens": inp, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": write}}}, ensure_ascii=False)


def _fake_transcript(tmp_path, lines):
    p = tmp_path / "abc.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


# ────────────────────────────────── context_tokens

def test_讀得到最後一輪的_context(C, tmp_path, monkeypatch):
    path = _fake_transcript(tmp_path, [
        _usage_line(read=10_000), "{}", _usage_line(read=200_000, write=5_000)])
    monkeypatch.setattr(C, "_transcript", lambda cid: path)
    assert C.context_tokens("abc") == 205_000


def test_只讀檔尾也要正確(C, tmp_path, monkeypatch):
    """⛔ transcript 有 300 MB，整份讀會讓每則訊息卡住 —— 所以只讀檔尾。

    ⚠️ 檔尾切下來的第一行可能是半行，要丟掉；這裡塞一堆墊檔行把
       真正的 usage 擠到檔尾之外的位置，確認它仍讀得到最後那一筆。
    """
    filler = [json.dumps({"pad": "x" * 900}) for _ in range(500)]   # 遠大於 256 KB
    path = _fake_transcript(tmp_path, filler + [_usage_line(read=333_000)])
    monkeypatch.setattr(C, "_transcript", lambda cid: path)
    assert os.path.getsize(path) > C._TAIL_BYTES, u"墊檔不夠大，這條沒測到東西"
    assert C.context_tokens("abc") == 333_000


def test_找不到_transcript_回0而不是爆掉(C, monkeypatch):
    monkeypatch.setattr(C, "_transcript", lambda cid: None)
    assert C.context_tokens("abc") == 0
    assert C.context_tokens("") == 0


def test_壞行不影響(C, tmp_path, monkeypatch):
    path = _fake_transcript(tmp_path, [
        _usage_line(read=50_000), '{"usage": 這不是JSON', "亂碼"])
    monkeypatch.setattr(C, "_transcript", lambda cid: path)
    assert C.context_tokens("abc") == 50_000


# ────────────────────────────────── threshold / plan

def test_門檻優先序_任務蓋設定檔(C):
    assert C.threshold({"compact_tokens": 200_000}) == 200_000
    assert C.threshold({"compact_tokens": 0}) == 0          # 0 ＝ 關閉
    assert C.threshold({}) > 0                               # 有預設


def test_門檻寫壞不要爆(C):
    assert C.threshold({"compact_tokens": "很多"}) == C.DEFAULT_THRESHOLD


def test_該不該壓的三種情況(C, monkeypatch):
    monkeypatch.setattr(C, "context_tokens", lambda cid: 300_000)
    assert C.plan({}) is None, u"還沒接上前文就沒東西可壓"
    assert C.plan({"claude_session_id": "x", "compact_tokens": 0}) is None, u"0 應該是關閉"
    got = C.plan({"claude_session_id": "x", "compact_tokens": 150_000})
    assert got == {"tokens": 300_000, "threshold": 150_000}
    monkeypatch.setattr(C, "context_tokens", lambda cid: 100_000)
    assert C.plan({"claude_session_id": "x", "compact_tokens": 150_000}) is None


# ────────────────────────────────── maybe_compact：失敗路徑最重要

#: 一份**像樣的**接手摘要 —— 刻意寫到真實長度，因為 `MIN_SUMMARY` 就是靠長度判的。
SUMMARY = u"""## 進度
貢獻度報表六項驗到第三項；分類帳與利潤率頁的守恆式已對過。

## 已確認的事實
· 貢獻度合計 1234.56，與分類帳逐筆加總一致（第 3 頁，GetContribution）
· 全站取整為 2dp，貢獻度沒有單獨向上取整
· 期號 20260826-045 已結算，playerCount 才寫得進去

## 已排除
· 不是快取問題 —— 換無痕視窗重載值一樣
· 不是權限問題 —— 主帳號與子帳號看到同一組數字

## 環境現況
總監2（b1.d2.crux.qat）／netsub2；建了兩筆注單當樣本，**尚未退碼**（要留給 CRUX-100）。

## 下一步
驗第四項「逐下級展開」，先開報表頁把表頭欄位抄下來。
"""


def _ask_ok(*a, **k):
    yield {"type": "text", "text": SUMMARY}


def _ask_short(*a, **k):
    yield {"type": "text", "text": u"好的。"}


def _ask_err(*a, **k):
    yield {"type": "error", "message": u"逾時"}


def _ask_boom(*a, **k):
    raise RuntimeError("claude 掛了")
    yield  # pragma: no cover


def _meta(**kw):
    m = {"id": "s1", "claude_session_id": "old-cid", "compact_tokens": 100_000}
    m.update(kw)
    return m


@pytest.mark.parametrize("ask,why", [
    (_ask_short, u"摘要太短（被拒答／只回一句好的）"),
    (_ask_err, u"摘要回合出錯"),
    (_ask_boom, u"claude 整個掛掉"),
])
def test_壓縮失敗時絕不可丟掉舊session(C, monkeypatch, ask, why):
    """★ 這是本模組最重要的一條。

    ⛔ 失敗時若把 `claude_session_id` 清掉，等於把**整段工作記憶換成一句廢話** ——
       比不壓縮糟糕得多：任務會從頭再來，而且不知道自己忘了什麼。
    """
    monkeypatch.setattr(C, "context_tokens", lambda cid: 300_000)
    m = _meta()
    saved = []
    assert C.maybe_compact("s1", m, ask=ask, save=saved.append) == "", why
    assert m["claude_session_id"] == "old-cid", u"%s 卻把舊 session 丟了" % why
    assert "compact_count" not in m, u"%s 卻記成壓縮過了" % why
    assert saved == [], u"%s 不該寫 meta" % why


def test_壓縮成功時清掉舊cid並記錄(C, monkeypatch):
    monkeypatch.setattr(C, "context_tokens", lambda cid: 300_000)
    monkeypatch.setattr(C, "_first_user_message", lambda sid: u"任務提示原文")
    m = _meta()
    saved = []
    seed = C.maybe_compact("s1", m, ask=_ask_ok, save=saved.append)
    assert seed, u"該壓縮卻沒回種子"
    assert m["claude_session_id"] is None, u"沒清掉舊 cid，下一則還是會 --resume"
    assert m["compacted_from"] == "old-cid"
    assert m["compact_count"] == 1
    assert m["compacted_at_tokens"] == 300_000
    assert saved and saved[0] is m


def test_摘要像樣但太空洞也要拒絕(C, monkeypatch):
    """⚠️ 不是只擋「好的。」—— **看起來有結構、內容卻空洞**的也要擋。

    ⭐ 代價不對稱：判錯成「太短」只是這次不壓縮（照常 --resume，毫無損失）；
       放行一份殘缺摘要則是整段工作記憶沒了。所以寧可偏嚴。
    """
    monkeypatch.setattr(C, "context_tokens", lambda cid: 300_000)
    terse = u"## 進度\n做了一些\n\n## 下一步\n繼續"
    assert len(terse) < C.MIN_SUMMARY, u"這條的前提壞了，terse 已經不算短"
    m = _meta()
    got = C.maybe_compact("s1", m, ask=lambda *a, **k: iter(
        [{"type": "text", "text": terse}]), save=None)
    assert got == "", u"空洞摘要被放行了"
    assert m["claude_session_id"] == "old-cid", u"空洞摘要卻把舊 session 丟了"


def test_中文密度高的完整摘要不可以被誤擋(C):
    """★ 這條是實作時真的踩到的（2026-08-26，連續兩次）。

    我自己寫的、內容完整的六節摘要只有 **159 字** —— 中文密度高。
    當時的門檻是「長度 < 200 就拒絕」，結果**合格的摘要被擋掉**，
    功能等於永遠不會觸發。⛔ 安全的失敗方向若把功能整個關掉，那不叫安全。

    所以判準改成「**有結構** ＋ 不是空殼」，長度只當底線。
    """
    dense = u"""## 進度
驗到第三項。
## 已確認的事實
合計 1234.56，與分類帳一致（GetContribution 第 3 頁）；全站 2dp。
## 已排除
不是快取（無痕重載一樣）；不是權限（主子帳號同值）。
## 環境現況
總監2／netsub2，建了兩筆注單尚未退碼。
## 下一步
驗逐下級展開，先抄表頭欄位。"""
    assert len(dense.strip()) < 200, u"這條的前提壞了 —— 範例已經不短了"
    assert C.looks_like_summary(dense), u"完整的中文摘要被誤擋，功能永遠不會觸發"


def test_空殼與廢話都要擋(C):
    assert not C.looks_like_summary(u"好的。")
    assert not C.looks_like_summary(u"## 進度\n做了一些\n\n## 下一步\n繼續"), u"有結構但空洞"
    assert not C.looks_like_summary(u"字" * 300), u"夠長但沒有任何結構"
    assert not C.looks_like_summary("")


def test_不需要壓縮時什麼都不做(C, monkeypatch):
    monkeypatch.setattr(C, "context_tokens", lambda cid: 50_000)
    m = _meta()
    assert C.maybe_compact("s1", m, ask=_ask_ok, save=None) == ""
    assert m["claude_session_id"] == "old-cid"


# ────────────────────────────────── 種子

def test_種子要帶原任務提示而不只是摘要(C, monkeypatch):
    """⛔ 只給摘要的話，接手的 session **不知道草稿區塊格式**，交不出產出。

    任務提示裡有前言、安全邊界、以及 ①~⑤ 的固定區塊格式 —— 那些是產出的契約。
    """
    monkeypatch.setattr(C, "_first_user_message",
                        lambda sid: u"kind     doc\nbody     完整的 markdown")
    seed = C.build_seed("s1", SUMMARY)
    assert u"kind     doc" in seed, u"種子沒帶任務提示 —— 接手的交不出草稿"
    assert u"貢獻度合計 1234.56" in seed, u"種子沒帶摘要"
    assert u"你是接手的" in seed, u"沒講清楚這是延續，它會從頭再做一次"
    assert u"不必重交" in seed, u"沒講草稿還在，它會把交過的再交一次"


def test_摘要提示不要它動工具(C):
    """⚠️ 摘要回合若跑起工具，等於在最貴的 context 上又加一輪。"""
    p = C.SUMMARY_PROMPT
    assert u"不要用工具" in p
    assert u"不要憑印象補完" in p, u"沒擋住編造 —— 接手的會把這份當事實用"
    assert "{tokens}" in p, u"少了佔位，人看不到壓縮發生在多大的 context"


# ────────────────────────────────── SSE 的進度回饋

def test_進度事件必須在壓縮開始之前送出():
    """★ 2026-08-26 首次實跑抓到的缺陷 —— 我自己寫的註解說「先送出進度事件」，

    程式碼卻是**壓縮跑完才送**。於是 509k 的 context 壓了一分多鐘，
    畫面全程靜止，看起來像卡死 —— 而「畫面完全沒有反應」正是這條路
    當初從非串流改成 SSE 要解決的問題。

    ⚠️ 這條用原始碼順序判：壓縮那一步是同步阻塞的，要驗「誰先 yield」
       就得真的跑起 claude。順序寫錯是唯一的失效方式，釘住順序就夠。
    """
    src = io.open(os.path.join(PLATFORM, "web_ui", "api", "chat.py"),
                  encoding="utf-8").read()
    body = src[src.index("def chat_stream("):]
    i_plan = body.index("_compact_plan(m)")
    i_yield = body.index("正在換一份較短的工作記憶")
    i_do = body.index("_take_seed(sid, m, _p)")
    assert i_plan < i_yield < i_do, \
        u"進度事件沒有先送 —— 壓縮期間畫面會靜止，看起來像卡死"
    # ⭐ 失敗也要講：否則畫面停在「正在換」，比沒講更像卡死
    assert "換工作記憶沒成功" in body, u"壓縮失敗時沒有回饋，畫面會停在「正在換」"


# ────────────────────────────────── Review 找到的兩個缺陷

def _chat(monkeypatch, disk, msgs=None):
    """載入 chat 模組並把 meta 的讀寫接到一個假磁碟。

    ⚠️ `save_meta` 一定要做成**整份覆寫**（真的那支是 `write_json_atomic`）——
       先前這裡寫成 `disk.update(mm)`，於是「刪掉某個鍵」在假磁碟上永遠不生效，
       **假的比真的寬鬆就會藏 bug**（2026-08-26 寫這批測試時當場踩到）。
    """
    CH = _load("web_ui.api.chat")

    def _save(mm):
        disk.clear()
        disk.update(mm)

    monkeypatch.setattr(CH, "get_meta", lambda sid: dict(disk))
    monkeypatch.setattr(CH, "save_meta", _save)
    monkeypatch.setattr(CH, "append_message",
                        lambda sid, role, text, **kw: (msgs if msgs is not None
                                                       else []).append((role, text)))
    return CH


def test_壓縮不可以蓋掉本輪其他步驟寫的_meta(C, monkeypatch):
    """🔴 Review 找到的缺陷① —— 先讀後寫競態。

    `chat()` 開頭取的 `m` 是快照，之後 `append_message` 與 `mark_running`
    各自「重讀→改→存」。壓縮若把過期的 `m` **整份**存回去，
    `activity="running"` 就沒了 —— 而 `note_tool` 檢查它，於是
    **整輪的工具進度都不會被記錄**（`commit` skill §8.4 的同一顆坑）。
    """
    disk = {"id": "s1", "activity": "running", "activity_prompt": u"探索分類帳",
            "message_count": 17, "claude_session_id": "old-cid"}
    CH = _chat(monkeypatch, disk)
    stale = {"id": "s1", "claude_session_id": None, "compact_count": 1,
             "compacted_at_tokens": 509_312, "compacted_from": "old-cid",
             "last_summary": u"## 進度\n驗到第三項"}
    CH._persist_compact("s1", stale, u"種子")

    assert disk["activity"] == "running", u"把 activity 蓋掉了 → 整輪工具進度不會記錄"
    assert disk["activity_prompt"] == u"探索分類帳", u"把本輪的提示摘要蓋掉了"
    assert disk["message_count"] == 17, u"把 message_count 倒退了"
    assert disk["compact_count"] == 1 and disk["claude_session_id"] is None
    assert disk["pending_seed"] == u"種子"


def test_摘要要留成一則訊息(C, monkeypatch):
    """⚠️ Review 找到的缺口③ —— 摘要是這次交接的唯一產物。"""
    disk, msgs = {"id": "s1"}, []
    CH = _chat(monkeypatch, disk, msgs)
    CH._persist_compact("s1", {"compacted_at_tokens": 509_312,
                               "last_summary": u"## 進度\n驗到第三項"}, u"種子")
    assert msgs and msgs[0][0] == "system", u"摘要沒留下來，交接漏了東西就查不到"
    assert u"驗到第三項" in msgs[0][1]
    assert "last_summary" not in disk, u"⛔ 別把長文存進 meta —— 每輪都要整份讀寫"


def test_壓縮後那一輪失敗_種子不可以遺失(C, monkeypatch):
    """🔴 Review 找到的缺陷② —— 最該避免的結果，卻是這個功能自己造成的。

    壓縮把 `claude_session_id` 清成 None，種子只前置到**那一則**提示。
    該回合若死在 `_init` 之前（啟動失敗／立刻逾時／連線中斷），
    cid 記不到、種子也沒了 → 下一則會開一個**零脈絡**的新 session，
    而它不知道自己忘了什麼。
    """
    disk = {"id": "s1", "claude_session_id": None, "pending_seed": u"上次的種子"}
    CH = _chat(monkeypatch, disk)
    monkeypatch.setattr(CH, "_compact_if_needed", lambda sid, m, p=None: ("", ""))

    seed, note = CH._take_seed("s1", dict(disk))
    assert seed == u"上次的種子", u"種子遺失 —— 下一輪會是零脈絡的新 session"
    assert u"沿用" in note, u"沒告訴人這是沿用上次的"


def test_落檔失敗要還原成壓縮前而不是變成零脈絡(C, monkeypatch):
    """🔴 修缺陷② 時**自己引入**的新缺陷（2026-08-26 冒煙測試當場抓到）。

    `maybe_compact` 已經把 `claude_session_id` 清成 None 了。若 `_persist_compact`
    拋錯就這樣回 ""，這一輪會用 `resume=None` 開一個**零脈絡**的新 session，
    而種子也沒落檔 —— 正好就是缺陷② 本身，只是換成由「落檔失敗」觸發。
    ⭐ 正解：白花一次摘要回合，換「照常 --resume 舊 session」。
    """
    disk = {"id": "s1"}
    CH = _chat(monkeypatch, disk)
    monkeypatch.setattr(CH.session_compact, "plan",
                        lambda m: {"tokens": 300_000, "threshold": 150_000})

    def _fake_compact(sid, meta, **kw):
        meta["compacted_from"] = meta["claude_session_id"]
        meta["claude_session_id"] = None        # 真的那支就是這樣改的
        return u"種子"

    monkeypatch.setattr(CH.session_compact, "maybe_compact", _fake_compact)
    monkeypatch.setattr(CH, "_persist_compact",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("磁碟滿了")))

    m = {"id": "s1", "claude_session_id": "old-cid"}
    assert CH._compact_if_needed("s1", m) == ("", "")
    assert m["claude_session_id"] == "old-cid", \
        u"落檔失敗卻沒還原 → 這一輪會開零脈絡的新 session，等於缺陷② 又回來"


def test_接上新session才清掉種子(C, monkeypatch):
    """⛔ 清太早等於缺陷② 又回來了 —— 這一輪死在半路時下一輪還要靠它。"""
    disk = {"id": "s1", "claude_session_id": None, "pending_seed": u"種子"}
    CH = _chat(monkeypatch, disk)

    CH._remember_claude_session("s1", {})                 # 沒有 cid ＝ 沒接上
    assert disk.get("pending_seed") == u"種子", u"還沒接上就把種子清了"

    CH._remember_claude_session("s1", {"session_id": "new-cid"})
    assert disk["claude_session_id"] == "new-cid"
    assert "pending_seed" not in disk, u"接上了卻沒清 —— 種子會被重複前置"


# ────────────────────────────────── 安全網

def test_autocompact_安全網有下且夾在合法範圍(monkeypatch):
    """⚠️ CLI 只收 100k~1M，超範圍會讓 claude **整支起不來**。

    設定寫錯不該讓平台的對話全掛，所以一律夾住。
    """
    S = _load("core.claude_session")
    argv = S.build_argv("hi")
    assert "--autocompact" in argv
    v = int(argv[argv.index("--autocompact") + 1])
    assert 100_000 <= v <= 1_000_000

    monkeypatch.setattr(S, "load_config", None, raising=False)
    cfg = _load("core.config")
    monkeypatch.setattr(cfg, "load_config", lambda: {"claude": {"autocompact_tokens": 50}})
    assert S._autocompact_tokens() == 100_000, u"太小沒夾住 → claude 起不來"
    monkeypatch.setattr(cfg, "load_config", lambda: {"claude": {"autocompact_tokens": 9 ** 9}})
    assert S._autocompact_tokens() == 1_000_000, u"太大沒夾住"


def test_安全網門檻要遠高於邊界壓縮門檻(C):
    """⛔ 兩者角色不同：安全網設低了就退化成「途中壓縮」，

    而那正是邊界壓縮要避開的失效模式（證據鏈是收工才寫成草稿的）。
    """
    S = _load("core.claude_session")
    assert S.DEFAULT_AUTOCOMPACT >= C.DEFAULT_THRESHOLD * 3, \
        u"安全網離邊界門檻太近，會在任務途中觸發"
