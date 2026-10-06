# -*- coding: utf-8 -*-
"""`scripts/stamp_shots.py`（MCP 截圖搬移＋蓋標注標記）的回歸測試。

用途：這支腳本是 MCP 截圖流程的最後一步 —— 它若靜默失敗，圖會進 `shots/` 卻沒有
      `qa-annotated` 標記，`lint_bug_assets` 的 W7 就會把**明明標注過**的圖判成未標注。
      兩個守門（檔名規範、覆蓋既有檔）也必須真的擋得住，否則等於沒有。
前置條件：無（全部在 tmp_path 上操作，不碰真實 docs/）。
使用方式：`pytest tests/tooling/test_stamp_shots.py -q`
"""
import os
import struct
import sys
import zlib

import pytest

import stamp_shots
from qa_common.shot import read_png_mark

import bug_paths as _bp
# ⚠️ 這個檔的測試都需要**一個已登記的產品**當樣本（腳本的 `--product` 有 choices 驗證）。
#    全新範本「一個產品都還沒接」是正常狀態 —— 那時候沒有東西可測，明講跳過。
#    ⛔ 不要靠 `bug_paths` 的 fallback 變出產品來：那個 fallback 只給「設定檔壞掉」用，
#       拿它來餵測試會讓「空工作區」這個狀態永遠測不到（2026-08-23）。
_REGISTERED = _bp.PRODUCTS
pytestmark = pytest.mark.skipif(
    not _REGISTERED,
    reason="這個工作區還沒接任何產品 —— 這幾條測的是「對某個產品」的腳本行為")
_SAMPLE = _REGISTERED[0] if _REGISTERED else ""
# ⚠️ 樣本產品的 docs 目錄名一併動態取 —— 不可寫死 "CRUX"：
#    config/products.json 重置後可能只剩其他產品（如「新綜合」），
#    寫死會讓 sandbox 建的目錄跟腳本實際查的目錄對不上（2026-09-16）。
_DOCS_DIR = _bp.PRODUCT_DIRS[_SAMPLE] if _REGISTERED else ""



def _png(path):
    """產生一張最小的合法 PNG（1×1），供搬移測試用。"""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    return path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把腳本的 ROOT 指到 tmp_path，建出 docs/<樣本產品>/bugs/shots/ 與一張來源圖。"""
    shots = tmp_path / "docs" / _DOCS_DIR / "bugs" / "shots"
    shots.mkdir(parents=True)
    monkeypatch.setattr(stamp_shots, "ROOT", str(tmp_path))
    src = _png(str(tmp_path / "src" / "raw.png"))
    return tmp_path, shots, src


def _run(*argv):
    """以 argv 執行 main()，回傳 exit code。"""
    old = sys.argv
    sys.argv = ["stamp_shots.py"] + list(argv)
    try:
        return stamp_shots.main()
    finally:
        sys.argv = old


# ── 正常路徑 ────────────────────────────────────────────────────

def test_搬移後會蓋上標注標記(sandbox):
    _, shots, src = sandbox
    rc = _run("--product", _SAMPLE, f"{src}=CRUX-060_01_說明.png")
    assert rc == 0
    dst = shots / "CRUX-060_01_說明.png"
    assert dst.exists(), "檔案沒被搬過去"
    assert read_png_mark(str(dst)) == "marks=mcp", \
        "搬過去了卻沒蓋標記 —— lint W7 會誤判成未標注，正是本腳本要解決的問題"


def test_來源檔不被搬走(sandbox):
    """用 copy 不用 move —— `.playwright-mcp/` 的原圖要留著供重截／比對。"""
    _, _, src = sandbox
    _run("--product", _SAMPLE, f"{src}=CRUX-060_01_說明.png")
    assert os.path.exists(src)


def test_dry_run_不寫任何檔(sandbox):
    _, shots, src = sandbox
    assert _run("--product", _SAMPLE, "--dry-run", f"{src}=CRUX-060_01_說明.png") == 0
    assert not (shots / "CRUX-060_01_說明.png").exists()


@pytest.mark.parametrize("name", [
    "CRUX-060_01_說明.png",              # 一般 bug 單
    "CRUX-037_fixed_01_修好了.png",       # 修復驗證圖
    "CRUX-S01_01_改善建議.png",           # ★ -S01 序列（改善建議，不佔 bug 流水號）
    "JIRA-CRUX-882_fixed_01_他人單.png",  # 純他人單，加 JIRA- 前綴避免撞命名空間
])
def test_合規檔名皆被接受(sandbox, name):
    _, shots, src = sandbox
    assert _run("--product", _SAMPLE, f"{src}={name}") == 0, f"{name} 應被接受"
    assert (shots / name).exists()


# ── 兩個守門 ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "probe.png",                 # 探索暫存名
    "CRUX-060_說明.png",          # 缺序號
    "CRUX-060_1_說明.png",        # 序號非 2 碼
    "crux-060_01_說明.png",       # 前綴小寫
])
def test_不合規檔名被擋下(sandbox, name):
    _, shots, src = sandbox
    assert _run("--product", _SAMPLE, f"{src}={name}") == 1, f"{name} 應被拒絕"
    assert not (shots / name).exists(), "被判不合規卻仍搬了檔"


def test_覆蓋既有檔要加force(sandbox):
    _, shots, src = sandbox
    target = "CRUX-060_01_說明.png"
    assert _run("--product", _SAMPLE, f"{src}={target}") == 0
    (shots / target).write_bytes(b"\x89PNG\r\n\x1a\n" + b"placeholder")   # 假裝已被改過

    assert _run("--product", _SAMPLE, f"{src}={target}") == 1, "沒有 --force 就不該覆蓋"
    assert (shots / target).read_bytes().endswith(b"placeholder"), "被無聲覆蓋了"

    assert _run("--product", _SAMPLE, "--force", f"{src}={target}") == 0
    assert read_png_mark(str(shots / target)) == "marks=mcp"


def test_有任何一項不合規就整批不執行(sandbox):
    """避免「前三張搬了、第四張才報錯」的半套狀態。"""
    _, shots, src = sandbox
    src2 = _png(str(sandbox[0] / "src" / "raw2.png"))
    rc = _run("--product", _SAMPLE, f"{src}=CRUX-060_01_好的.png", f"{src2}=壞的.png")
    assert rc == 1
    assert not (shots / "CRUX-060_01_好的.png").exists(), \
        "有一項不合規時仍搬了另一項 —— 應該整批不執行"


def test_來源不存在會回錯而非靜默略過(sandbox):
    _, shots, _ = sandbox
    assert _run("--product", _SAMPLE, "no/such/file.png=CRUX-060_01_說明.png") == 1
    assert not (shots / "CRUX-060_01_說明.png").exists()


def test_glob_沒比對到檔案也算輸入有問題(sandbox):
    """回傳碼契約：0 成功／1 輸入有問題（整批未執行）／2 環境問題（找不到 shots 目錄）。"""
    tmp, shots, _ = sandbox
    assert _run("--product", _SAMPLE, str(tmp / "src" / "nothing-*.png")) == 1
    assert not any(shots.iterdir())


def test_找不到shots目錄回2(tmp_path, monkeypatch):
    monkeypatch.setattr(stamp_shots, "ROOT", str(tmp_path))     # 沒有 docs/CRUX/bugs/shots
    src = _png(str(tmp_path / "src" / "raw.png"))
    assert _run("--product", _SAMPLE, f"{src}=CRUX-060_01_說明.png") == 2


def test_搬成功會在來源旁留filed記號(sandbox):
    """⭐ 本腳本是**複製**不是搬移，原檔會留在來源目錄 ——
    呼叫端（平台的「待搬」提醒）需要一個方式知道「這張已經歸位了」。
    ⛔ 少了它，已經搬完的圖會一直被報成待辦，而**假的待辦會讓人開始忽略真的**
    （2026-08-25 補拍任務實跑撞到）。
    """
    _, _shots, src = sandbox
    assert _run("--product", _SAMPLE, f"{src}=CRUX-060_01_說明.png") == 0
    mark = src + ".filed"
    assert os.path.exists(mark), "沒留記號 —— 待搬提醒會一直重複"
    with open(mark, encoding="utf-8") as f:
        assert "CRUX-060_01_說明.png" in f.read()


def test_可以指定來源標記(sandbox):
    """平台代搬用 `auto`，不可冒用 `mcp` —— 那是「session 自己搬」的來源值，
    日後查一張圖的來歷全靠它分辨。"""
    _, shots, src = sandbox
    assert _run("--product", _SAMPLE, "--mark", "auto",
                f"{src}=CRUX-060_02_說明.png") == 0
    assert read_png_mark(str(shots / "CRUX-060_02_說明.png")) == "marks=auto"
