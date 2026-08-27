# -*- coding: utf-8 -*-
"""PytestAdapter：真的把 pytest 跑起來（階段 C，2026-08-23）。

用途：`ui_tests` 這支標準內建工具接上它就活了 —— 選案例 → 執行 → 即時進度 →
      allure 報告 → 失敗分類。在此之前 `adapters/pytest_.py` 根本不存在，
      run 型命令沒有任何實作。

使用方式：由 `runner/manager.py` 呼叫，不直接用。
    adapter.start(StartRequest(...))   # 起子程序，背景執行緒盯 progress.jsonl
    adapter.status(run_id) / logs / reports / stop

前置條件與三個陷阱（全部踩過，違反會**靜默失真**）：

  1. ⛔ **子程序不可寫 `run_status.json`** —— `core/jsonio.py` 的鎖是
     `threading.Lock`（程序內），跨程序無效。故 pytest plugin 只 append
     `progress.jsonl`，**本檔（父程序）是唯一寫入者**。
  2. ⛔ **pytest exit code 1 ＝「有案例失敗」，不是「run 失敗」** ——
     必須映射成 `completed`，否則 `run_index` 的 `hourly_heat`
     會把每次紅燈都算成基礎設施故障。
     真正的失敗（2=中斷、3=內部錯誤、4=用法錯誤）才是 `failed`。
  3. ⛔ **`--alluredir` 必須覆蓋** —— `pyproject.toml` 的 addopts 無條件帶
     `reports/allure-results`，不覆蓋的話所有 run 互相污染，還弄髒工作區的正式報告。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

from adapters.base import ArtifactRef, RunHandle, StartRequest, ToolAdapter
from adapters.argv import build_invocation
from core import run_store as rs

# pytest 的退出碼語意（`pytest.ExitCode`）
_EXIT_OK = 0
_EXIT_TESTS_FAILED = 1        # ★ 有案例失敗 —— run 本身是成功跑完的
_EXIT_INTERRUPTED = 2
_EXIT_INTERNAL_ERROR = 3
_EXIT_USAGE_ERROR = 4
_EXIT_NO_TESTS = 5

_POLL_SEC = 0.4


class PytestAdapter(ToolAdapter):
    kind = "pytest"

    def __init__(self, spec, ctx=None):
        super().__init__(spec, ctx)
        self._procs: dict[str, subprocess.Popen] = {}

    # ────────────────────────────────── 同步命令
    def run_command(self, command: dict, params: dict) -> dict:
        """目前只有「重建案例索引」。

        ⚠️ 先前 `PytestAdapter` **沒有實作這個方法**，於是 `ui_tests.tool.json`
           宣告的 `rebuild_index` 按鈕看得到、按下去必定回
           「ui_tests 不支援同步命令」（2026-08-23 範本端到端驗收第 ⑧ 步）。
           重建邏輯本來就在 `collect/case_index.rebuild()`，只差沒有接上來。
        """
        if command.get("id") != "rebuild_index":
            return super().run_command(command, params)
        from collect.case_index import compute_signature, rebuild
        # ⚠️ 鍵是 `watch_globs`（不是 `watch`）—— 打錯不會報錯，
        #    只會讓簽章永遠算成空的，於是索引「重建了但立刻又被判為過期」。
        sig = compute_signature(
            (self.spec.raw.get("cases") or {}).get("watch_globs") or [])
        idx = rebuild(self.spec, sig)
        if idx.get("error"):
            return {"ok": False, "kind": "text",
                    "text": "重建失敗：%s" % idx["error"]}
        return {"ok": True, "kind": "text",
                "text": "案例索引已重建：%d 條 · %s"
                        % (idx.get("count", 0), idx.get("generated_at", ""))}

    # ────────────────────────────────── 案例索引
    def list_cases(self, *, refresh: bool = False) -> dict | None:
        """把既有案例交出去（`base` 的預設回 `None`，等於什麼都沒有）。

        ⚠️ 呼叫端一律寫成 `(… or {}).get("flat") or []` —— 少了這個覆寫**不會報錯**，
           只會讓「既有案例」永遠是 0 條。代價是規則式生成器找不到任何結構範本，
           產出全部退化成 `confidence: low`（2026-08-23 用 CRUX 實跑範本時發現，
           `existing_count` 明明有 698 條索引卻回 0）。
        """
        from collect.case_index import build_or_load
        return build_or_load(self.spec, refresh=refresh)

    # ────────────────────────────────── 執行
    def start(self, req: StartRequest) -> RunHandle:
        cmd = self.spec.command(req.command_id)
        run_dir = req.platform_run_dir
        # ⚠️ 一定要給 `run_dir` —— `selection` 欄位的 emit 是 `argsfile`，
        #    沒有 run_dir 就只會得到「<清單.txt：N 行>」這種預覽用佔位字串。
        #    選取的案例由 argsfile（`@檔案`）帶進去，**不要再自己 append 一次**。
        inv = build_invocation(self.spec, cmd, req.params, run_dir=run_dir)
        argv = list(inv["argv"])

        # 完全沒選時才退回 cases.roots 宣告的整棵樹
        if not req.selection and not (req.params or {}).get("selection"):
            argv += list((self.spec.cases or {}).get("roots") or ["tests"])

        # ★ 陷阱 3：一定要覆蓋 pyproject 的 addopts
        argv += ["--alluredir", os.path.join(run_dir, "allure-results")]
        # ★ 陷阱 1：進度只走 append-only 的 jsonl
        argv += ["-p", "tools.test_platform.collect.pytest_progress",
                 "--progress-out", os.path.join(run_dir, "progress.jsonl")]

        env = dict(os.environ)
        env.update({k: str(v) for k, v in inv["env"].items()})
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        rs.append_console(req.run_id, "$ " + inv["redacted"]["cmdline"])
        rs.append_console(req.run_id, "（選取 %d 條案例）" % len(req.selection)
                          if req.selection else "（未選取，跑整棵案例樹）")

        console = open(rs.console_path(req.run_id), "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(argv, cwd=inv["cwd"], env=env,
                                stdout=console, stderr=subprocess.STDOUT)
        self._procs[req.run_id] = proc
        threading.Thread(target=self._watch, args=(req.run_id, proc, run_dir, console),
                         daemon=True, name="pytest-%s" % req.run_id).start()
        return RunHandle(run_id=req.run_id, pid=proc.pid)

    # ────────────────────────────────── 背景盯梢（父程序是唯一寫入者）
    def _watch(self, run_id, proc, run_dir, console):
        pfile = os.path.join(run_dir, "progress.jsonl")
        offset = 0
        last = {"counts": {}, "total": 0, "done": 0, "failed_cases": []}
        self._phase(run_id, "collecting")
        try:
            while True:
                offset, events = _read_new(pfile, offset)
                for ev in events:
                    last = _apply(run_id, ev, last, self.spec)
                if proc.poll() is not None:
                    offset, events = _read_new(pfile, offset)   # 收尾再讀一次
                    for ev in events:
                        last = _apply(run_id, ev, last, self.spec)
                    break
                time.sleep(_POLL_SEC)
        finally:
            try:
                console.close()
            except OSError:
                pass
        self._finish(run_id, proc.returncode, last, run_dir)

    def _phase(self, run_id, tool_phase, **extra):
        """更新工具階段，並在第一次看到工具階段時把**平台 phase** 推進到 `running`。

        ⚠️ `manager.start()` 只設到 `starting`，先前**沒有人負責推到 `running`**
        —— 於是整個執行期間都顯示「啟動中」，儀表板的「執行中 N」也算不對。
        （與 `adapters/cli.py` 同一個修正，2026-08-23。）
        """
        pm = self.spec.phase_meta(tool_phase)
        cur = (rs.read_status(run_id) or {}).get("phase")
        if cur == "starting":
            extra.setdefault("phase", "running")
        rs.update_status(run_id, tool_phase=tool_phase, tool_phase_label=pm.get("label"),
                         tool_phase_tone=pm.get("tone"), **extra)

    def _finish(self, run_id, code, last, run_dir):
        st = rs.read_status(run_id) or {}
        if st.get("phase") == "stopping" or os.path.isfile(os.path.join(run_dir, "stop.flag")):
            phase = "stopped"
        elif code in (_EXIT_OK, _EXIT_TESTS_FAILED, _EXIT_NO_TESTS):
            # ★ 陷阱 2：有案例失敗 ≠ run 失敗
            phase = "completed"
        else:
            phase = "failed"

        c = last.get("counts") or {}
        summary = {
            "kind": "pytest",
            "passed": c.get("passed", 0),
            "failed": c.get("failed", 0) + c.get("error", 0),
            "skipped": c.get("skipped", 0),
            "failed_cases": last.get("failed_cases") or [],
            "exit_code": code,
        }
        if phase == "failed":
            summary["note"] = {
                _EXIT_INTERRUPTED: "執行被中斷（Ctrl-C 或外部訊號）",
                _EXIT_INTERNAL_ERROR: "pytest 內部錯誤 —— 多半是 conftest 或 plugin 壞了",
                _EXIT_USAGE_ERROR: "命令列用法錯誤 —— 檢查 argv 與參數宣告",
            }.get(code, "pytest 以退出碼 %s 結束" % code)

        # ★ C-3：接上既有的 `scripts/analyze_run.py` 三分類（真失敗／前置未備／環境問題）
        #    ⛔ 不在平台裡重寫規則 —— 兩份會漂移，而症狀是「終端機與平台結論不同」。
        try:
            from core.run_analysis import classify_run, summary_line
            meta = rs.read_meta(run_id) if hasattr(rs, "read_meta") else {}
            analysis = classify_run(run_dir, (meta or {}).get("product"))
            if analysis:
                summary["analysis"] = analysis
                summary["analysis_line"] = summary_line(analysis)
        except Exception as e:                 # 分類失敗不該讓整個 run 收尾失敗
            summary["analysis_error"] = str(e)[:200]

        self._phase(run_id, "generating_reports")
        # ★ `generate_allure` 先前是 **inert 欄位** —— 宣告了、預設開、表單看得到，
        #   但沒有任何程式讀它，也從來沒有人跑過 `allure generate`，
        #   於是 `reports()` 找 `allure-report/index.html` 永遠找不到
        #   （2026-08-23 範本端到端驗收）。
        meta_all = (rs.read_meta(run_id) if hasattr(rs, "read_meta") else {}) or {}
        want_allure = (meta_all.get("params") or {}).get("generate_allure", True)
        if want_allure and phase != "stopped":
            from core.allure_cli import generate as _gen
            gok, gdetail = _gen(os.path.join(run_dir, "allure-results"),
                                os.path.join(run_dir, "allure-report"))
            # ⚠️ 產不出報告**不改變 run 的成敗** —— 案例已經跑完了。
            #    但要把原因寫進 summary，否則使用者只看到「沒有報告」。
            summary["allure"] = {"generated": gok, "detail": gdetail}
            rs.append_console(run_id, "allure：%s" % gdetail)
        artifacts = [a.to_dict() for a in self.reports(run_id)]
        rs.update_status(run_id, phase=phase, exit_code=code, summary=summary,
                         artifacts=artifacts,
                         tool_phase=phase if phase != "completed" else "completed",
                         tool_phase_label={"completed": "完成", "failed": "失敗",
                                           "stopped": "已停止"}[phase],
                         tool_phase_tone={"completed": "success", "failed": "danger",
                                          "stopped": "warn"}[phase])
        # ⛔ **一定要釋放併發佔位** —— `manager._acquire_slot()` 用
        #    `ended_ts is None` 判斷「還在跑」，而它只在 `on_finished()` 裡設。
        #    不呼叫的話，第一次跑完之後這支工具就**再也啟動不了**（訊息還說
        #    「已有進行中的 run」），直到重啟平台。
        #    （當時只有 Demo 的 FakeAdapter 會呼叫，所以接真之前看不出來）
        #    （2026-08-23 情境 B 走查）。
        try:
            from runner import manager as _mgr
            _mgr.on_finished(run_id)
        except Exception:                  # noqa: BLE001 —— 釋放失敗不該讓收尾失敗
            pass
        self._procs.pop(run_id, None)

    # ────────────────────────────────── 契約其餘部分
    def stop(self, run_id: str, *, force: bool = False, reason: str = "user") -> dict:
        rs.update_status(run_id, phase="stopping", stop_reason=reason)
        proc = self._procs.get(run_id)
        if proc and proc.poll() is None:
            _kill_tree(proc.pid, force=force)
        return rs.read_status(run_id) or {"run_id": run_id}

    def status(self, run_id: str) -> dict:
        return rs.read_status(run_id) or {"run_id": run_id}

    def logs(self, run_id: str, offset: int = 0, limit_bytes: int = 262144) -> dict:
        return rs.tail_console(run_id, offset=offset, limit_bytes=limit_bytes)

    def reports(self, run_id: str) -> list[ArtifactRef]:
        d = rs.run_dir(run_id)
        out = [ArtifactRef(key="console", label="執行輸出",
                           href="/reports/%s/console.log" % run_id, kind="text")]
        idx = os.path.join(d, "allure-report", "index.html")
        if os.path.isfile(idx):
            out.append(ArtifactRef(key="allure", label="Allure 報告",
                                   href="/reports/%s/allure-report/index.html" % run_id,
                                   kind="html", primary=True))
        elif os.path.isdir(os.path.join(d, "allure-results")):
            out.append(ArtifactRef(
                key="allure_results", label="Allure 原始結果（尚未 generate）",
                href="/reports/%s/allure-results" % run_id, kind="json", exists=True))
        return out


# ────────────────────────────────── 小工具

def _read_new(path, offset):
    """從 offset 起讀新的完整行。回 (新 offset, [事件])。

    ⚠️ 只讀完整行 —— 子程序可能正寫到一半，殘行留到下一輪再讀。
    """
    if not os.path.isfile(path):
        return offset, []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            data = f.read()
            cut = data.rfind("\n")
            if cut < 0:
                return offset, []
            events = []
            for line in data[:cut].splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
            return offset + cut + 1, events
    except OSError:
        return offset, []


def _apply(run_id, ev, last, spec):
    """把一則進度事件寫進 run_status（**父程序是唯一寫入者**）。"""
    kind = ev.get("event")
    if kind == "collected":
        last["total"] = ev.get("total", 0)
        rs.update_status(run_id, progress={"current": 0, "total": last["total"],
                                           "percent": 0, "label": "已收集 %d 條" % last["total"]})
        pm = spec.phase_meta("running")
        rs.update_status(run_id, tool_phase="running", tool_phase_label=pm.get("label"),
                         tool_phase_tone=pm.get("tone"))
    elif kind == "test":
        last["counts"] = ev.get("counts") or {}
        done, total = ev.get("done", 0), ev.get("total", 0) or 1
        c = last["counts"]
        rs.update_status(
            run_id,
            progress={"current": done, "total": total,
                      "percent": round(done / total * 100, 1),
                      "label": (ev.get("title") or ev.get("nodeid", ""))[:60]},
            metrics={"passed": c.get("passed", 0),
                     "failed": c.get("failed", 0) + c.get("error", 0),
                     "skipped": c.get("skipped", 0)},
            summary={"kind": "pytest", "passed": c.get("passed", 0),
                     "failed": c.get("failed", 0) + c.get("error", 0),
                     "skipped": c.get("skipped", 0)})
    elif kind == "finished":
        last["counts"] = ev.get("counts") or last.get("counts") or {}
        last["failed_cases"] = ev.get("failed_cases") or []
    return last


def _kill_tree(pid, force=False):
    """殺整棵程序樹。

    ⚠️ pytest 會起 playwright 的瀏覽器子程序 —— 只殺父程序的話瀏覽器會留下來。
    """
    try:
        import psutil
        p = psutil.Process(pid)
        for ch in p.children(recursive=True):
            try:
                ch.kill() if force else ch.terminate()
            except psutil.Error:
                pass
        p.kill() if force else p.terminate()
    except Exception:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
