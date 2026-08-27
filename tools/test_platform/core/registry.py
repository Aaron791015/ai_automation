"""工具註冊表：載入／驗證 registry/*.tool.json 與 products.json。

用途：平台核心對工具的唯一認識來源。平台程式碼不認得任何工具的參數，只認 ToolSpec 的欄位。
使用方式：
    from core.registry import get_registry
    reg = get_registry(); reg.tools; reg.products; reg.tool("crux_perf")
    python -m core.registry --validate      # 驗證全部 spec，有錯 exit 1
前置條件：registry/_schema.json 定義結構；本檔做輕量結構檢查（不引 jsonschema 相依）。
"""
from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from core.jsonio import read_json
from core.paths import REGISTRY_DIR, repo_path

_KINDS = {"cli", "pytest", "http"}
_MODES = {"run", "sync", "python_call", "http"}
_FIELD_TYPES = {"text", "number", "boolean", "select", "multiselect", "textarea", "secret",
                "duration", "file_select", "number_list", "case_picker", "path_picker"}
_EMITS = {"opt", "opt_eq", "flag_when_true", "flag_when_false", "repeat", "join", "json",
          "env", "positional", "argsfile", "none"}


@dataclass
class ToolSpec:
    raw: dict
    path: str

    @property
    def id(self) -> str: return self.raw["id"]
    @property
    def name(self) -> str: return self.raw.get("name", self.id)
    @property
    def kind(self) -> str: return self.raw.get("kind", "cli")
    @property
    def scope(self) -> str:
        """`product`（預設）或 `workspace`。

        `workspace` ＝ 這支工具**不屬於任何產品**（初始化、lint、覆蓋率盤點…）。
        它在 UI 上歸「工作區」分組，且豁免「product／products 必填」。
        （2026-08-23 階段 B：初始化介面需要它，而這是可複用的宣告能力，
        不是為單一工具開的後門。）
        """
        return self.raw.get("scope", "product")

    @property
    def is_workspace(self) -> bool:
        return self.scope == "workspace"

    @property
    def products(self) -> list[str]:
        """本工具涵蓋哪些產品。

        `"products": "*"` ＝ **跟著 `config/products.json` 動態展開**（不含偽產品）——
        標準內建工具（如 `ui_tests`）不該硬編碼產品清單，
        否則同事接了自己的產品還要回頭改 tool.json（2026-08-23 階段 A）。
        """
        raw = self.raw.get("products")
        if raw == "*":
            return [p["id"] for p in load_registry().products if not p.get("virtual")]
        if raw is not None:
            return list(raw)
        if self.is_workspace:
            return []            # 工作區工具不屬於任何產品
        return [self.raw.get("product", "common")]
    @property
    def product(self) -> str:
        ps = self.products
        return ps[0] if ps else "workspace"
    @property
    def enabled(self) -> bool: return self.raw.get("enabled", True)
    @property
    def demo(self) -> bool: return bool(self.raw.get("demo"))
    @property
    def live(self) -> bool:
        """⚠️ **已無作用的遺留欄位**（2026-08-24 標註）。

        先前它是「覆蓋全域 demo 模式」的宣告 —— 讓純本機唯讀的工具即使在 demo 模式下
        也走真 adapter。**2026-08-23 移除 demo 模式之後，平台一律真的執行**，
        這個宣告就沒有任何意義了；目前沒有任何呼叫端讀它。

        三支壓測的 tool.json 還留著 `"live": true`（無害的未知鍵）。
        要清掉的話由各壓測線自己動（`commit` skill §8.3：tool.json 依 tool_id 歸該產品線），
        已登記在共通交接檔 T26。
        """
        return bool(self.raw.get("live"))
    @property
    def danger(self) -> dict: return self.raw.get("danger") or {"level": "low"}
    @property
    def commands(self) -> list[dict]: return self.raw.get("commands", [])
    @property
    def run(self) -> dict: return self.raw.get("run") or {}
    @property
    def stop(self) -> dict: return self.raw.get("stop") or {"strategy": "tree"}
    @property
    def artifacts(self) -> dict: return self.raw.get("artifacts") or {}
    @property
    def runtime(self) -> dict: return self.raw.get("runtime") or {}
    @property
    def cases(self) -> dict | None: return self.raw.get("cases")
    @property
    def phases(self) -> list[dict]: return self.run.get("phases", [])

    def command(self, cmd_id: str | None) -> dict | None:
        if cmd_id is None:
            for c in self.commands:
                if c.get("primary"):
                    return c
            return self.commands[0] if self.commands else None
        for c in self.commands:
            if c["id"] == cmd_id:
                return c
        return None

    def phase_meta(self, value: str | None) -> dict:
        for p in self.phases:
            if p["value"] == value:
                return p
        return {"value": value, "label": value or "—", "tone": "info"}

    def public(self) -> dict:
        """給前端的完整描述（不含任何敏感值；spec 本身也不該含）。"""
        d = dict(self.raw)
        # ⚠️ 一律回**解析後**的產品清單，不可原樣送出 `"*"` ——
        #    前端 `byProd` 做的是 `(t.products).includes(pid)`，
        #    `["*"].includes("crux")` 是 false → 該工具會從所有產品欄消失
        #    （2026-08-23 實際啟動平台才發現）。
        d["products"] = self.products
        d["scope"] = self.scope
        d["product"] = self.product
        d["danger"] = self.danger
        return d


@dataclass
class Registry:
    products: list[dict] = field(default_factory=list)
    tools: dict[str, ToolSpec] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    # 不擋載入、但值得讓人看到的提醒（目前只有 spec_version 落後的升級建議）
    notes: list[dict] = field(default_factory=list)

    def tool(self, tool_id: str) -> ToolSpec:
        if tool_id not in self.tools:
            raise KeyError(f"未知的工具：{tool_id}")
        return self.tools[tool_id]

    def product(self, pid: str) -> dict | None:
        return next((p for p in self.products if p["id"] == pid), None)

    def tools_of(self, pid: str) -> list[ToolSpec]:
        return sorted((t for t in self.tools.values() if pid in t.products),
                      key=lambda t: (t.raw.get("order", 99), t.id))


# ── spec 版本 ────────────────────────────────────────────────
#
# 範本會演進：本輪就替 `runtime` 加了 `run_id_arg`、`scope`、`products: "*"`。
# 同事手上的 tool.json 是**匯出當下的快照**，schema 改了之後兩邊就會對不上。
#
# ⚠️ 沒有這一層時的失效方式最難查：`validate_spec` 報一句
#   「缺必要欄位 X」，而**那支工具直接從 `#/tools` 與儀表板消失** ——
#   錯誤只出現在 `#/registry` 這個平常不會去看的頁面，
#   於是同事的感覺是「我的工具不見了」，而不是「我的 tool.json 該升級了」。
#
# 目前為 1。**加欄位不算破壞**（舊檔照樣通過），所以只有真的改掉既有欄位的
# 語義時才需要 +1 —— 屆時務必在下方的 `_SPEC_CHANGES` 寫明「要改什麼」。
SPEC_VERSION = 1

# 版本 → 從前一版升上來要做什麼（給人看的升級指引，不是程式邏輯）
_SPEC_CHANGES: dict[int, str] = {
    # 2: "把 xxx 改名為 yyy；`runtime.zzz` 現在必填",
}


def spec_version_note(raw: dict) -> dict | None:
    """比對 tool.json 的 `spec_version` 與平台當前版本。回 None ＝相容。

    回 {level, message}：`error`＝平台看不懂（來自更新的範本）；
    `warn`＝該升級了（仍可用，但可能少了新功能）。
    """
    v = raw.get("spec_version", 1)
    try:
        v = int(v)
    except (TypeError, ValueError):
        return {"level": "error",
                "message": "spec_version 不是整數（%r）—— 請對照 registry/_schema.json" % v}
    if v > SPEC_VERSION:
        return {"level": "error", "message":
                "這支 tool.json 的 spec_version=%d，比本平台支援的 %d 新 —— "
                "它多半來自較新版的範本。請更新平台（`tools/test_platform/`），"
                "或把該欄位降回 %d 並移除新版才有的欄位。"
                % (v, SPEC_VERSION, SPEC_VERSION)}
    if v < SPEC_VERSION:
        steps = "；".join(_SPEC_CHANGES.get(n, "（無說明）")
                          for n in range(v + 1, SPEC_VERSION + 1))
        return {"level": "warn", "message":
                "spec_version=%d，本平台已到 %d。仍可使用，但建議升級：%s"
                % (v, SPEC_VERSION, steps)}
    return None


def _check(cond: bool, errors: list, path: str, msg: str) -> None:
    if not cond:
        errors.append({"file": path, "error": msg})


def validate_spec(raw: dict, path: str) -> list[dict]:
    """輕量結構檢查，回傳錯誤清單（空＝通過）。

    ⚠️ 有錯誤時該工具會被**整支略過**（不會出現在 `#/tools` 與儀表板），
    所以訊息一律要寫得能直接照做，不能只說「缺欄位 X」。
    """
    errs: list[dict] = []
    note = spec_version_note(raw)
    if note and note["level"] == "error":
        return [{"file": path, "error": note["message"]}]
    for k in ("id", "name", "kind", "commands"):
        _check(k in raw, errs, path, f"缺必要欄位 {k}")
    if errs:
        return errs
    _check(raw["kind"] in _KINDS, errs, path, f"kind 必須是 {sorted(_KINDS)}")
    _check(isinstance(raw["commands"], list) and raw["commands"], errs, path, "commands 至少一個")
    scope = raw.get("scope", "product")
    _check(scope in ("product", "workspace"), errs, path,
           'scope 需為 "product" 或 "workspace"')
    if scope != "workspace":
        _check("product" in raw or "products" in raw, errs, path,
               "需有 product 或 products（scope=workspace 的工具才可省略）")
    if "products" in raw:
        _check(raw["products"] == "*" or isinstance(raw["products"], list), errs, path,
               'products 需為陣列或 "*"（"*" ＝ 跟著 config/products.json 動態展開）')
    seen_cmd = set()
    for c in raw.get("commands", []):
        cid = c.get("id", "?")
        _check(cid not in seen_cmd, errs, path, f"命令 id 重複：{cid}")
        seen_cmd.add(cid)
        _check(c.get("mode") in _MODES, errs, path, f"命令 {cid} 的 mode 必須是 {sorted(_MODES)}")
        if c.get("mode") == "python_call":
            _check(":" in (c.get("call") or ""), errs, path, f"命令 {cid} 的 call 需為 module:function")
        # 條件式與 group 都是「打錯不會報錯、只會靜默失效」的地雷，所以在這裡擋掉：
        #   · group 打錯 → form.js 依 group 過濾欄位，撈不到就整個欄位不渲染
        #   · *_when 的 key 打錯 → 條件永遠不成立，欄位永遠不出現
        params = c.get("params") or {}
        group_ids = {g.get("id") for g in (params.get("groups") or [])}
        field_keys = {f.get("key") for f in params.get("fields", [])}
        for f in params.get("fields", []):
            fk = f.get("key", "?")
            _check(f.get("type") in _FIELD_TYPES, errs, path, f"欄位 {cid}.{fk} 的 type 不合法：{f.get('type')}")
            if group_ids:
                # ⛔ **沒填 group 跟填錯 group 一樣糟** —— `renderForm` 是
                #    `fields.filter(f => (f.group||'_') === g.id)`，沒填的落在 `_`，
                #    不屬於任何一組 → **整個欄位不渲染**，而且表單看起來完全正常。
                #    2026-08-24 實查：三支壓測工具共 19 個欄位這樣被吃掉，
                #    `perf_field_parity` 全綠（它只看宣告，不看畫不畫得出來）。
                _check(f.get("group"), errs, path,
                       f"欄位 {cid}.{fk} 沒有 group，但這個命令宣告了 groups"
                       f"（欄位會靜默不顯示）—— 請填 {sorted(g for g in group_ids if g)} 之一")
                if f.get("group"):
                    _check(f["group"] in group_ids, errs, path,
                           f"欄位 {cid}.{fk} 的 group「{f['group']}」不在 groups 內（欄位會靜默不顯示）")
            for ck in ("visible_when", "available_when", "required_when"):
                for k in (f.get(ck) or {}):
                    # `_` 開頭是平台注入的虛擬欄位（如 _products），不必宣告成 field
                    _check(k.startswith("_") or k in field_keys, errs, path,
                           f"欄位 {cid}.{fk} 的 {ck} 參照了不存在的欄位「{k}」（條件永遠不成立）")
            if f.get("emit"):
                _check(f["emit"] in _EMITS, errs, path, f"欄位 {cid}.{fk} 的 emit 不合法：{f['emit']}")
            if f.get("emit") == "env":
                _check(bool(f.get("env")), errs, path, f"欄位 {cid}.{fk} emit=env 需有 env")
            if f.get("type") == "secret":
                _check(f.get("emit") == "env", errs, path, f"secret 欄位 {cid}.{fk} 必須 emit=env（不進命令列）")
                _check(f.get("never_persist", True), errs, path, f"secret 欄位 {cid}.{fk} 不可 never_persist=false")

        # ⭐ next：跑完之後的導引（2026-08-24 走查盲點 ②）。
        #    宣告錯了會**靜默不顯示** —— 與 group／options_from 同一種失效形狀，所以要驗。
        for n in (c.get("next") or []):
            _check(bool(n.get("label")) and bool(n.get("href")), errs, path,
                   f"命令 {cid} 的 next 少了 label 或 href")
            _check(n.get("when") in (None, "ok", "fail"), errs, path,
                   f"命令 {cid} 的 next.when 只能是 ok／fail")
            # ⛔ 只放行站內 hash 路由 —— `next` 是宣告式的，不該變成開任意網址的口
            _check(str(n.get("href", "")).startswith("#/"), errs, path,
                   f"命令 {cid} 的 next.href 只能是站內路由（#/…）")
    if raw["kind"] == "pytest":
        _check(isinstance(raw.get("cases"), dict), errs, path, "kind=pytest 需有 cases 區塊")
    return errs


def to_slug(pid: str) -> str:
    """把任何一種寫法的產品名正規化成**平台的 slug**（`crux`／`wbot`／`qixing`）。

    ⛔ 這個工作區有**兩套產品 id**（`core/registry.py` 的 `_merge_products` 有完整說明）：
       `config/products.json` 用權威 id（`CRUX`、`七星`、`投注機器人`），
       平台內部用小寫 slug（URL、tool.json 的鍵、索引的分層鍵）。

    ⚠️ **凡是「外面傳進來的產品名」都要先過這一支**（MCP 參數、query string、
       session 打的字）—— 否則 `by_prod.get("CRUX")` 拿到 `None`，
       而多數呼叫端會把 `None` 當成「這個產品沒有資料」而回 0。

    2026-08-24 實測到的實例：對話裡問「CRUX 有幾張活躍 Bug」，
    session 用權威 id `CRUX` 呼叫 MCP 的 `get_bugs` → **回 0 張**，
    而畫面上寫著 60 張。回答錯得很有自信，且完全不會報錯。
    """
    if not pid:
        return pid
    want = str(pid).strip().lower()
    try:
        for p in get_registry().products:
            cands = [p.get("id"), p.get("product_id"), p.get("label"),
                     p.get("short"), p.get("wordmark")]
            cands += list(p.get("aliases") or [])
            if any(c and str(c).strip().lower() == want for c in cands):
                return p.get("id") or pid
    except Exception:                           # noqa: BLE001
        pass
    return pid


def load_workspace_products() -> list[dict]:
    """讀工作區的 `config/products.json`（★ 產品定義的單一來源）。

    讀不到就回空 —— 平台仍能靠 registry 的偽產品運作，不會整個掛掉
    （剛匯出的範本就是 products 為空的狀態）。
    """
    path = os.path.join(repo_path("config"), "products.json")
    data = read_json(path, {}) or {}
    return data.get("products") or []


_cache: Registry | None = None


# 呈現層沒設定時的預設配色（依序取用，用完循環）——
# ⚠️ 不可因為同事沒設呈現層就不顯示他的產品，那正是他會遇到的狀態。
_FALLBACK_COLORS = ["#4fa9ff", "#8f8cff", "#59d3a4", "#ffb454", "#ff7a9c", "#7ad9ff"]


def _merge_products(display: list[dict]) -> list[dict]:
    """`config/products.json`（單一來源）× `registry/products.json`（呈現層）。

    ★ 為什麼是這個方向（2026-08-23）：`config/products.json` 已被 bug_paths／lint_docs／
      reset_workspace／export_template 依賴，而**平台是選用的**（同事可以完全不開）——
      單一來源必須在不依賴平台的那一側。平台只保留它獨有的東西：slug、配色、徽章。

    ⚠️ 兩邊的 id 空間不同：
        config   id = `CRUX`／`投注機器人`／`七星`（中文大寫；Bug 前綴、lint --product、目錄名）
        平台     id = `crux`／`wbot`／`qixing`（小寫 slug；`#/product/<id>` 網址、tool.json 的鍵）
      → 以 config 的 `aliases[0]`（退回 `skill`）當 slug；合併後兩個都帶著。

    ⚠️ 平台有偽產品（如 `common` 共通），config 那份沒有 —— **保留並標 `virtual`**，
      它們不是產品，不參與知識雷達的產品掃描與交接檔檢查。
    """
    by_slug = {d.get("id"): d for d in display}
    out: list[dict] = []
    seen_slugs = set()

    for i, p in enumerate(load_workspace_products()):
        slug = (p.get("aliases") or [None])[0] or p.get("skill") or p.get("id")
        seen_slugs.add(slug)
        d = by_slug.get(slug, {})
        out.append({
            # ── 單一來源（config/products.json）────────────────
            "id": slug,                       # 平台內部一律用 slug（URL、tool.json 的鍵）
            "product_id": p["id"],            # 權威 id（Bug 前綴、lint --product）
            "bug_prefix": p.get("bug_prefix"),
            "skill": p.get("skill"),
            "jira_key": p.get("jira_key"),
            "knowledge": {
                "docs_dir": "docs/%s" % p.get("docs_dir", p["id"]),
                "bug_product": p["id"],
                "tests_prefix": "tests/%s/" % (p.get("tests_dir") or slug),
                "skill": p.get("skill"),
                "handover": list(p.get("handovers") or []),
            },
            # ── 呈現層（registry/products.json，缺了就給預設）──
            "label": d.get("label") or p.get("label") or p["id"],
            "short": d.get("short") or d.get("label") or p["id"],
            "wordmark": d.get("wordmark") or slug.upper(),
            "subtitle": d.get("subtitle", ""),
            "color": d.get("color") or _FALLBACK_COLORS[i % len(_FALLBACK_COLORS)],
            "env_badge": d.get("env_badge", ""),
            "hero_pillar": d.get("hero_pillar", True),
            "order": d.get("order", i + 1),
            "virtual": False,
        })

    # 平台獨有的偽產品（`common` 共通）—— config 那份沒有，但 tool.json 會引用
    for d in display:
        if d.get("id") in seen_slugs:
            continue
        v = dict(d)
        v["virtual"] = True               # 不是產品：不掃知識雷達、不查交接檔
        v.setdefault("hero_pillar", False)
        out.append(v)

    # ⭐ `common` **由程式碼保證存在**，不依賴呈現層設定檔（2026-08-24）。
    #
    # 它是平台內建的概念（跨產品工具的歸屬：`workspace_ops`、`crux_bet_demo`…），
    # 而先前它只從 `registry/products.json` 來 —— 範本的骨架是 `{"products": []}`，
    # 於是**同事的平台一開起來就是** `workspace_ops 引用了不存在的產品：['common']`。
    #
    # ⛔ 不要改成「在骨架裡寫死 common」—— 那份檔案同事會改、`reset_workspace`
    #    會清。內建概念要由程式碼保證。
    if not any(p.get("id") == "common" for p in out):
        out.append({"id": "common", "label": "共通", "short": "共通",
                    "wordmark": "COMMON", "subtitle": "不屬於任何產品的工具",
                    "color": "#8b9bb4", "env_badge": "", "hero_pillar": False,
                    "order": 99, "virtual": True})

    return sorted(out, key=lambda p: p.get("order", 99))


def _source_signature() -> tuple:
    """registry 的來源檔簽章（mtime＋size）。任何一份變了，簽章就變。

    ⭐ 為什麼需要它：`_cache` 原本**只有 `force=True` 才重讀**，於是
       「接完產品 → 重新整理瀏覽器」什麼也不會發生 —— 而空狀態卡片正是
       這樣叫使用者做的。東西做對了、介面說沒做對，是 Day-0 最惡劣的失敗
       （2026-08-23 情境 A 走查）。
    """
    paths = [repo_path("config", "products.json"),
             os.path.join(REGISTRY_DIR, "products.json")]
    paths += sorted(glob.glob(os.path.join(REGISTRY_DIR, "*.tool.json")))
    sig = []
    for p in paths:
        try:
            st = os.stat(p)
            sig.append((os.path.basename(p), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((os.path.basename(p), 0, 0))
    return tuple(sig)


_cache_sig: tuple | None = None


def load_registry(force: bool = False) -> Registry:
    global _cache, _cache_sig
    sig = _source_signature()
    if _cache is not None and not force and sig == _cache_sig:
        return _cache
    _cache_sig = sig
    reg = Registry()
    prod = read_json(os.path.join(REGISTRY_DIR, "products.json"), {}) or {}
    reg.products = _merge_products(prod.get("products", []))
    for path in sorted(glob.glob(os.path.join(REGISTRY_DIR, "*.tool.json"))):
        raw = read_json(path)
        if raw is None:
            reg.errors.append({"file": os.path.basename(path), "error": "JSON 無法解析"})
            continue
        errs = validate_spec(raw, os.path.basename(path))
        if errs:
            reg.errors.extend(errs)
            continue
        expected = os.path.basename(path)[:-len(".tool.json")]
        if raw["id"] != expected:
            reg.errors.append({"file": os.path.basename(path), "error": f"id={raw['id']} 與檔名不一致（應為 {expected}）"})
            continue
        note = spec_version_note(raw)
        if note:                       # 只會是 warn（error 已在 validate_spec 擋掉）
            reg.notes.append({"file": os.path.basename(path), "note": note["message"]})
        reg.tools[raw["id"]] = ToolSpec(raw=raw, path=path)
    _cache = reg
    return reg


def get_registry() -> Registry:
    return load_registry()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    reg = load_registry(force=True)
    print(f"products: {len(reg.products)}  tools: {len(reg.tools)}")
    for t in reg.tools.values():
        print(f"  ✓ {t.id:16} {t.kind:7} {','.join(t.products):18} {t.name}")
    for e in reg.errors:
        print(f"  ✗ {e['file']}: {e['error']}")
    return 1 if reg.errors else 0


if __name__ == "__main__":
    sys.exit(main())
