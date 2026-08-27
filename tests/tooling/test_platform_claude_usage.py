# -*- coding: utf-8 -*-
"""Claude 用量統計（`core/claude_usage.py`，2026-08-25）。

用途：總覽狀態列的「Claude 用量」段與設定頁的用量明細，資料來自
      `~/.claude/projects/**/*.jsonl` 的 `usage` 欄位。這支測試釘住四件
      **錯了不會有任何錯誤訊息、只會默默給出錯誤數字**的事：

      ① ⛔ **同一則訊息會寫成多行**（每個 content block 一行）且 usage 原封重複 ——
         不依 message.id 去重會多算 2.25 倍（實測值，見模組檔頭）
      ② ⛔ **增量掃描的交界**：第二批的第一行若與第一批的最後一行同 id，仍要去重
      ③ ⛔ **寫到一半的行**不可以被算（Claude Code 正在寫入時很常見）
      ④ ⛔ **週限額的有無**依方案分流 —— 訂閱制有、API 金鑰／Bedrock／Vertex 沒有

前置條件：全部在 tmp_path 上操作，**不碰真的 ~/.claude**（projects_dir 與 CACHE_FILE 都被 monkeypatch）。
使用方式：`pytest tests/tooling/test_platform_claude_usage.py -q`
"""
import io
import json
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _u():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.claude_usage as U
    return U


def _ts(minutes_ago: int = 1) -> str:
    """UTC ISO 時戳（transcript 存的就是 UTC）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - minutes_ago * 60))


def _line(mid, ts, *, inp=1, out=10, cw=100, cr=1000, model="claude-sonnet-5", compact=True):
    o = {"type": "assistant", "timestamp": ts,
         "message": {"id": mid, "model": model,
                     "usage": {"input_tokens": inp, "output_tokens": out,
                               "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}}}
    # ⚠️ 真實 transcript 是緊湊格式；compact=False 用來驗「有空格也要算得到」
    return json.dumps(o, ensure_ascii=False, separators=((",", ":") if compact else (", ", ": ")))


@pytest.fixture(autouse=True)
def _no_live_by_default(monkeypatch):
    """⛔ 預設把即時額度關掉。

    不關的話，每一條快照測試都會拿**真的憑證**去打**真的端點** ——
    測試不該碰網路，也不該碰你的帳號（2026-08-25 加即時額度時當場發生）。
    要驗即時的那幾條自己用 `_live_env()` 打開。
    """
    U = _u()
    monkeypatch.setattr(U, "live_quota_enabled", lambda: False)
    monkeypatch.setattr(U, "_live", {"ts": 0.0, "data": None, "error": None, "running": False})


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    U = _u()
    proj = tmp_path / "projects" / "c--Fake-Repo"
    proj.mkdir(parents=True)
    monkeypatch.setattr(U, "CACHE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setattr(U, "projects_dir", lambda: str(tmp_path / "projects"))
    monkeypatch.setattr(U, "probe_claude", lambda *a, **k: {"logged_in": True, "auth": {
        "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}})
    return U, str(proj / "s1.jsonl")


def _write(path, lines, mode="w"):
    with io.open(path, mode, encoding="utf-8", newline="\n") as f:
        for ln in lines:
            f.write(ln + "\n")


# ─────────────────────────────── ① 去重（最貴的坑）

def test_同一則訊息的多個content_block只算一次(sandbox):
    U, f = sandbox
    _write(f, [_line("msg_A", _ts()), _line("msg_A", _ts()), _line("msg_A", _ts()),
               _line("msg_B", _ts())])
    s = U.usage_summary(wait=True)
    # 兩則訊息 × 每則 out=10 → 20；不去重的話會是 40
    assert s["windows"]["today"]["output"] == 20
    assert s["windows"]["today"]["messages"] == 2


def test_不同訊息不會被誤刪(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts()), _line("b", _ts()), _line("a", _ts())])
    # id 交錯出現（實測不會發生，但真發生時寧可多算也不要漏算整段）
    assert U.usage_summary(wait=True)["windows"]["today"]["messages"] == 3


# ─────────────────────────────── ② 增量掃描

def test_增量不重算舊資料(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts()), _line("b", _ts())])
    first = U.usage_summary(wait=True)["windows"]["today"]["output"]
    _write(f, [_line("c", _ts())], mode="a")
    second = U.usage_summary(wait=True)["windows"]["today"]["output"]
    assert first == 20 and second == 30       # 只加了新的那一則，沒有把前兩則重算


def test_增量交界的同一則訊息仍去重(sandbox):
    """⛔ 最容易漏的一種：第一批結尾與第二批開頭是同一則訊息的兩個 block。

    只靠「這一批之內比對上一行」會漏掉，所以 last_id 必須跨批次持久化。
    """
    U, f = sandbox
    _write(f, [_line("msg_X", _ts())])
    U.usage_summary(wait=True)
    _write(f, [_line("msg_X", _ts()), _line("msg_Y", _ts())], mode="a")
    s = U.usage_summary(wait=True)
    assert s["windows"]["today"]["messages"] == 2      # X 一次、Y 一次
    assert s["windows"]["today"]["output"] == 20


def test_寫到一半的行不算_補完才算(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts())])
    with io.open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(_line("b", _ts())[:40])              # 沒有換行 → 這一行還沒寫完
    assert U.usage_summary(wait=True)["windows"]["today"]["messages"] == 1
    with io.open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(_line("b", _ts())[40:] + "\n")       # ⚠️ 補完的是**同一行**的後半
    assert U.usage_summary(wait=True)["windows"]["today"]["messages"] == 2


def test_檔案縮水就整份重讀_算的是新內容(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts()), _line("b", _ts()), _line("c", _ts())])
    U.usage_summary(wait=True)
    _write(f, [_line("d", _ts())])                    # 覆寫成更短的內容
    s = U.usage_summary(wait=True)
    # ⭐ 檔案的內容就是那個檔的事實 —— 被換掉之後，舊的三則**已經不存在**了。
    #    先前的寫法把它們留著（「歷史不回頭刪」），那正是下面那條翻倍缺陷的根源。
    assert s["windows"]["today"]["messages"] == 1


def test_檔案被整個換掉時整份重讀_不會parse到半行(sandbox):
    """⛔ 增量最危險的失效：檔案被換成**更長**的內容，offset 指到中段。

    只比 size 的話 `size > start` 成立，會從中間開始 parse —— 半行垃圾被丟掉、
    後半的訊息被算進來，**數字錯了卻沒有任何錯誤訊息**。開頭雜湊就是為了擋這個。
    """
    U, f = sandbox
    _write(f, [_line("a", _ts()), _line("b", _ts())])
    U.usage_summary(wait=True)
    _write(f, [_line("x", _ts()), _line("y", _ts()), _line("z", _ts()),
               _line("w", _ts())])                     # 換成不同且更長的內容
    s = U.usage_summary(wait=True)
    assert s["windows"]["today"]["messages"] == 4      # 新檔完整的 4 則，一則不多一則不少


def test_整份重讀不會翻倍(sandbox, monkeypatch):
    """⛔ 2026-08-25 實際踩到的缺陷：桶掛在全域、重讀就再加一次 → 近 7 天 10.3B 變 20.7B。

    觸發整份重讀的路徑有三條（版本換代／開頭雜湊不符／檔案縮水），這裡用最常見的
    「版本換代」—— 範本每次更新 schema 都會走到。
    """
    U, f = sandbox
    _write(f, [_line(str(i), _ts()) for i in range(5)])
    first = U.usage_summary(wait=True)["windows"]["today"]
    assert first["messages"] == 5
    monkeypatch.setattr(U, "VERSION", U.VERSION + 1)   # 逼所有檔重讀
    again = U.usage_summary(wait=True)["windows"]["today"]
    assert again == first, "整份重讀之後數字必須一模一樣，翻倍就是這條在擋"


def test_重複掃描不會累加(sandbox):
    """沒有任何檔案變動時，掃十次的結果必須完全相同。"""
    U, f = sandbox
    _write(f, [_line("a", _ts()), _line("b", _ts())])
    base = U.usage_summary(wait=True)["windows"]["today"]
    for _ in range(9):
        assert U.usage_summary(wait=True)["windows"]["today"] == base


def test_檔案被刪掉_歷史折進孤兒桶不會憑空消失(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts()), _line("b", _ts())])
    U.usage_summary(wait=True)
    os.remove(f)
    s = U.usage_summary(wait=True)
    assert s["windows"]["today"]["messages"] == 2
    assert [p["name"] for p in s["by_project"]] == ["c--Fake-Repo"]


# ─────────────────────────────── ③ 解析的邊界

def test_冒號後有空格也要算得到(sandbox):
    """濾行的子字串若寫死 `"type":"assistant"`，換個序列化寫法就會靜默歸零。"""
    U, f = sandbox
    _write(f, [_line("a", _ts(), compact=False)])
    assert U.usage_summary(wait=True)["windows"]["today"]["messages"] == 1


def test_非assistant的行不算(sandbox):
    U, f = sandbox
    fake = json.dumps({"type": "user", "timestamp": _ts(),
                       "message": {"id": "u1", "usage": {"output_tokens": 999}},
                       "note": "這一行提到 assistant 這個字"}, ensure_ascii=False, separators=(",", ":"))
    _write(f, [fake, _line("a", _ts())])
    assert U.usage_summary(wait=True)["windows"]["today"]["output"] == 10


def test_壞掉的json不會讓整份掛掉(sandbox):
    U, f = sandbox
    _write(f, ['{"type":"assistant" 這行壞了', _line("a", _ts())])
    assert U.usage_summary(wait=True)["windows"]["today"]["messages"] == 1


def test_總量是四種token相加(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts(), inp=1, out=2, cw=4, cr=8)])
    t = U.usage_summary(wait=True)["windows"]["today"]
    assert t["total"] == 15 and (t["input"], t["output"], t["cache_write"], t["cache_read"]) == (1, 2, 4, 8)


def test_沒有transcript目錄時不崩(tmp_path, monkeypatch):
    U = _u()
    monkeypatch.setattr(U, "CACHE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setattr(U, "projects_dir", lambda: str(tmp_path / "不存在"))
    monkeypatch.setattr(U, "probe_claude", lambda *a, **k: {"logged_in": False, "auth": {}})
    s = U.usage_summary(wait=True)
    assert s["ready"] is True and s["available"] is False


# ─────────────────────────────── ④ 週限額分流（使用者點名的「有些人有、有些人沒有」）

@pytest.mark.parametrize("auth,weekly", [
    ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}, True),
    ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "pro"}, True),
    ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "team"}, True),
    ({"loggedIn": True, "authMethod": "apiKey", "apiProvider": "firstParty", "subscriptionType": ""}, False),
    ({"loggedIn": True, "authMethod": "bedrock", "apiProvider": "bedrock", "subscriptionType": ""}, False),
    ({"loggedIn": True, "authMethod": "vertex", "apiProvider": "vertex", "subscriptionType": ""}, False),
    ({}, False),
])
def test_週限額依方案分流(auth, weekly):
    U = _u()
    p = U.plan_of(auth)
    assert p["has_weekly"] is weekly
    assert p["label"] and p["note"]          # 兩個都要有，UI 直接顯示


def test_方案為訂閱時摘要帶得出週窗口(sandbox):
    U, f = sandbox
    _write(f, [_line("a", _ts())])
    s = U.usage_summary(wait=True)
    assert s["plan"]["has_weekly"] is True
    assert set(s["windows"]) == {"h5", "today", "week", "prev_week", "month"}
    assert len(s["spark"]) == 14


# ─────────────────────────────── ⑤ 分佈與本工作區

def test_by_model與by_project有值且過濾掉零(sandbox, tmp_path):
    U, f = sandbox
    other = tmp_path / "projects" / "D--Other"
    other.mkdir(parents=True)
    _write(f, [_line("a", _ts(), model="claude-opus-5"),
               _line("z", _ts(), model="<synthetic>", inp=0, out=0, cw=0, cr=0)])
    _write(str(other / "s.jsonl"), [_line("b", _ts(), model="claude-sonnet-5")])
    s = U.usage_summary(wait=True)
    assert [m["name"] for m in s["by_model"]] == ["claude-opus-5", "claude-sonnet-5"]   # <synthetic> 被濾掉
    assert {p["name"] for p in s["by_project"]} == {"c--Fake-Repo", "D--Other"}


# ─────────────────────────────── ⑥ 官方額度百分比（快取，會過期）

def _cjson(tmp_path, monkeypatch, U, *, fetched_ms, five=74, five_reset="2099-01-01T00:00:00+00:00",
           seven=56, seven_reset="2099-01-01T00:00:00+00:00", tier="default_claude_max_5x"):
    p = tmp_path / ".claude.json"
    io.open(p, "w", encoding="utf-8").write(json.dumps({
        "oauthAccount": {"organizationRateLimitTier": tier},
        "cachedUsageUtilization": {"fetchedAtMs": fetched_ms, "utilization": {
            "five_hour": {"utilization": five, "resets_at": five_reset},
            "seven_day": {"utilization": seven, "resets_at": seven_reset},
            "limits": [{"kind": "weekly_scoped", "percent": 27,
                        "resets_at": seven_reset, "scope": {"model": {"display_name": "Fable"}}}],
        }},
    }, ensure_ascii=False))
    monkeypatch.setattr(U, "claude_json_path", lambda: str(p))
    return U.read_utilization()


def test_額度百分比讀得到(tmp_path, monkeypatch):
    U = _u()
    q = _cjson(tmp_path, monkeypatch, U, fetched_ms=int(time.time() * 1000))
    assert q["available"] and q["usable"] and q["stale"] is False
    assert [(b["kind"], b["percent"]) for b in q["bars"]] == [("five_hour", 74), ("seven_day", 56)]
    assert q["tier_label"] == "Max 5×"
    assert q["scoped"] == [{"label": "Fable", "percent": 27,
                            "resets_at": "2099-01-01T00:00:00+00:00", "expired": False}]


def test_快照太舊就不可當現況(tmp_path, monkeypatch):
    """⛔ 過期的百分比**比沒有百分比更糟** —— 會被當成現在的水位。"""
    U = _u()
    old_ms = int((time.time() - 3 * 3600) * 1000)
    q = _cjson(tmp_path, monkeypatch, U, fetched_ms=old_ms)
    assert q["available"] and q["stale"] is True and q["usable"] is False
    assert q["fetched_at"] and q["age_sec"] > 3000       # 時間一定要帶出來給人看


def test_窗口已重置的那一格要標成過期(tmp_path, monkeypatch):
    U = _u()
    q = _cjson(tmp_path, monkeypatch, U, fetched_ms=int(time.time() * 1000),
               five_reset="2000-01-01T00:00:00+00:00")
    five = [b for b in q["bars"] if b["kind"] == "five_hour"][0]
    seven = [b for b in q["bars"] if b["kind"] == "seven_day"][0]
    assert five["expired"] is True and seven["expired"] is False
    assert q["usable"] is True          # 還有一格有效 → 整體仍可用，過期那格自己標


def test_兩格都過期就整體不可用(tmp_path, monkeypatch):
    U = _u()
    q = _cjson(tmp_path, monkeypatch, U, fetched_ms=int(time.time() * 1000),
               five_reset="2000-01-01T00:00:00+00:00", seven_reset="2000-01-01T00:00:00+00:00")
    assert q["usable"] is False


def test_沒有claude_json時不崩(tmp_path, monkeypatch):
    U = _u()
    monkeypatch.setattr(U, "claude_json_path", lambda: str(tmp_path / "不存在.json"))
    q = U.read_utilization()
    assert q["available"] is False and q["bars"] == [] and q["usable"] is False


def test_摘要帶得出quota(sandbox, tmp_path, monkeypatch):
    U, f = sandbox
    _write(f, [_line("a", _ts())])
    _cjson(tmp_path, monkeypatch, U, fetched_ms=int(time.time() * 1000))
    s = U.usage_summary(wait=True)
    assert s["quota"]["usable"] is True and len(s["quota"]["bars"]) == 2


# ─────────────────────────────── ⑦ 即時額度（平台自己打 /api/oauth/usage）

TOKEN = "sk-ant-oat-THIS-MUST-NEVER-LEAK"


class _Resp:
    def __init__(self, code=200, body=None, text=""):
        self.status_code, self._body, self.text = code, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _live_env(tmp_path, monkeypatch, U, *, exp_min=60, resp=None, boom=None):
    """把憑證檔與 requests 都換掉，回傳「這次打了幾次、帶了什麼 header」的紀錄。"""
    cred = tmp_path / ".credentials.json"
    io.open(cred, "w", encoding="utf-8").write(json.dumps({"claudeAiOauth": {
        "accessToken": TOKEN, "expiresAt": int((time.time() + exp_min * 60) * 1000),
        "rateLimitTier": "default_claude_max_5x"}}, ensure_ascii=False))
    monkeypatch.setattr(U, "CRED_PATH", str(cred))
    monkeypatch.setattr(U, "live_quota_enabled", lambda: True)   # 蓋掉 autouse 的預設關閉
    monkeypatch.setattr(U, "_live", {"ts": 0.0, "data": None, "error": None, "running": False})
    calls = []

    class _FakeRequests:
        @staticmethod
        def get(url, timeout=None, headers=None):
            calls.append({"url": url, "headers": headers or {}})
            if boom:
                raise boom
            return resp if resp is not None else _Resp(200, _body())

    monkeypatch.setitem(sys.modules, "requests", _FakeRequests)
    return calls


def _body(five=24, seven=89):
    far = "2099-01-01T00:00:00+00:00"
    return {"five_hour": {"utilization": five, "resets_at": far},
            "seven_day": {"utilization": seven, "resets_at": far},
            "limits": [{"kind": "weekly_scoped", "percent": 27, "resets_at": far,
                        "scope": {"model": {"display_name": "Fable"}}}]}


def test_即時額度打得到且標成live(tmp_path, monkeypatch):
    U = _u()
    calls = _live_env(tmp_path, monkeypatch, U)
    q = U.read_utilization()
    assert q["live"] is True and q["usable"] is True and q["stale"] is False
    assert [(b["kind"], b["percent"]) for b in q["bars"]] == [("five_hour", 24), ("seven_day", 89)]
    assert q["tier_label"] == "Max 5×"
    assert len(calls) == 1
    assert calls[0]["url"] == U.QUOTA_API
    assert calls[0]["headers"]["anthropic-beta"] == U.QUOTA_BETA


def test_五分鐘內不重打_force才重打(tmp_path, monkeypatch):
    U = _u()
    calls = _live_env(tmp_path, monkeypatch, U)
    for _ in range(5):
        U.read_utilization()
    assert len(calls) == 1, "節流沒生效，總覽每 60 秒問一次會把端點打爆"
    U.read_utilization(force=True)
    assert len(calls) == 2, "force 要繞過節流（↻ 按鈕靠它）"


def test_token過期就不打_改走快照(tmp_path, monkeypatch):
    U = _u()
    calls = _live_env(tmp_path, monkeypatch, U, exp_min=-1)      # 已過期
    monkeypatch.setattr(U, "claude_json_path", lambda: str(tmp_path / "不存在.json"))
    q = U.read_utilization()
    assert calls == [], "token 過期還去打只會拿 401"
    assert q["live"] is False and q["available"] is False
    assert "過期" in (q["live_error"] or "")


@pytest.mark.parametrize("kw,expect", [
    ({"resp": _Resp(401, {})}, "HTTP 401"),
    ({"resp": _Resp(200, None)}, "不是 JSON"),
    ({"resp": _Resp(200, {"nope": 1})}, "five_hour"),
    ({"boom": OSError("連線被拒")}, "OSError"),
])
def test_各種失敗都安靜退回快照(tmp_path, monkeypatch, kw, expect):
    """⛔ 一個看板數字不值得把整頁弄壞 —— 失敗一律降級，而且要講得出為什麼。"""
    U = _u()
    _live_env(tmp_path, monkeypatch, U, **kw)
    snap = tmp_path / ".claude.json"
    io.open(snap, "w", encoding="utf-8").write(json.dumps({
        "oauthAccount": {"organizationRateLimitTier": "default_claude_max_5x"},
        "cachedUsageUtilization": {"fetchedAtMs": int(time.time() * 1000),
                                   "utilization": _body(11, 22)}}, ensure_ascii=False))
    monkeypatch.setattr(U, "claude_json_path", lambda: str(snap))
    q = U.read_utilization()
    assert q["live"] is False, "失敗了就不可以自稱 live"
    assert expect in (q["live_error"] or ""), q["live_error"]
    assert [b["percent"] for b in q["bars"]] == [11, 22], "要退回快照的數字"


def test_token絕不出現在任何回傳裡(sandbox, tmp_path, monkeypatch):
    """⛔ 最重要的一條：OAuth token 只能在記憶體裡流動。"""
    U, f = sandbox
    _write(f, [_line("a", _ts())])
    _live_env(tmp_path, monkeypatch, U)
    blob = json.dumps(U.usage_summary(wait=True), ensure_ascii=False, default=str)
    assert TOKEN not in blob
    assert "accessToken" not in blob
    assert "Bearer" not in blob


def test_失敗訊息也不可以夾帶token(tmp_path, monkeypatch):
    """錯誤訊息是最常見的洩漏途徑 —— 例外原文可能含整串 URL 與 header。"""
    U = _u()
    _live_env(tmp_path, monkeypatch, U, boom=RuntimeError("boom " + TOKEN))
    q = U.read_utilization()
    assert TOKEN not in json.dumps(q, ensure_ascii=False, default=str)


def test_可以整條關掉(tmp_path, monkeypatch):
    U = _u()
    calls = _live_env(tmp_path, monkeypatch, U)
    monkeypatch.setattr(U, "live_quota_enabled", lambda: False)
    monkeypatch.setattr(U, "claude_json_path", lambda: str(tmp_path / "不存在.json"))
    q = U.read_utilization()
    assert calls == [] and q["live"] is False


def test_project_key把路徑轉成目錄名():
    """⚠️ 不可以斷言 repo 的名字 —— 這支測試會跟著範本發給同事，在他的目錄下跑。

    （2026-08-25 原本寫 `"automation" in k`，匯出的範本一跑就紅燈。）
    """
    U = _u()
    k = U.project_key(os.path.join(ROOT, "tools", "test_platform"))
    assert k.endswith("-tools-test_platform")            # 分隔符全變 `-`，底線保留
    assert not any(c in k for c in (":", "/", chr(92), " "))
