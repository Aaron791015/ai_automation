"""CliAdapter：把 registry 宣告的命令真的以 subprocess 跑起來。

用途：兩種命令形態都走這裡。
      · **sync** —— `crux_bet_demo` 的四個命令（秒～分鐘級、純本機唯讀、不碰站台）
      · **run** —— 三支壓測的 `bet_load`／`chat_load`（長時間、要能看進度與中途停止）

⚠️ run 型的三個要點（2026-08-23 實作，都是實測踩出來的）：

1. **進度讀引擎自己寫的 `run_status.json`**，不從 console 字串猜 ——
   路徑與欄位由 tool.json 的 `run.status_source` 宣告，階段的中文 label
   由 `run.phases` 宣告。這兩份**早就寫好了，只是先前沒有消費者**。
2. **引擎有自己的 run 目錄**（`<工具>/logs/runs/<run_id>/`）。宣告
   `runtime.run_id_arg` 的直接對上平台的 run_id；沒宣告的只能事後探測 ——
   探測是猜的，**同時跑兩個 run 就可能認錯**，所以能開 CLI 就別靠探測。
   （三支壓測現在都宣告了 `--run-id`；wbot 那支是 2026-08-23 為此補的，
     連帶發現它的 `resolve_params()` 根本沒讀 body 的 `run_id`，
     外部指定的值被**靜默丟掉**。）
3. **停止有兩種策略**（`stop.strategy`）：`tree` 直接殺整棵程序樹；
   `flag` 先寫 `stop.flag` 讓 worker 優雅收尾並產報告，逾時才殺。
   ⛔ 一律殺**整棵樹** —— 壓測的孫程序握著 WebSocket，
   只殺父程序它們會留下來**繼續下注**（真金流）。
使用方式：由 `adapters/__init__.py` 的 get_adapter() 依 spec.kind 建立，呼叫端只認 ToolAdapter 介面。
前置條件：
    · argv 由 `adapters/argv.py` 依欄位的 emit 規則組出，本檔不認得任何工具的參數。
    · 腳本要能吐「單一 JSON 物件」才解析得出結構化結果 —— 靠 `runtime.json_flag`
      宣告那個旗標（`crux_bet_demo` 是 `--json-out`）。沒宣告就退回純文字結果。
    · stdout 可能混著 loguru 之類的雜訊，所以是**從最後一行往前找第一個解析得出的 JSON**。
"""
from __future__ import annotations

import json
import os
import shutil
import shlex
import subprocess
import threading
import time

from adapters.argv import build_invocation
import core.run_store as rs
from core.paths import REPO_ROOT, rel_to_repo
from adapters.base import ArtifactRef, RunHandle, StartRequest, ToolAdapter

_MAX_TEXT = 20000


_POLL_SEC = 1.0


class CliAdapter(ToolAdapter):
    kind = "cli"

    def __init__(self, spec, ctx=None):
        super().__init__(spec, ctx)
        self._procs: dict[str, subprocess.Popen] = {}
        # run_id → 引擎自己的 run 目錄（`stop.flag` 與報告都在那裡，不在平台的 run 目錄）
        self._engine_dirs: dict[str, str | None] = {}

    # ---- run 型 ----
    def start(self, req: StartRequest) -> RunHandle:
        """起一個長時間執行的引擎程序，並在背景盯梢到它結束。

        與 `PytestAdapter.start` 同骨架；CLI 型多做兩件事：
        · 若 `runtime.run_id_arg` 有宣告，就把**平台的 run_id 交給引擎**，
          讓兩邊的 run 目錄對得上（CRUX／七星有 `--run-id`）。
        · 沒宣告的（wbot）改用 `_engine_run_dir` 事後認出引擎自己開的目錄 ——
          `stop.flag` 一定要寫進**引擎的** run 目錄才有效。
        """
        cmd = self.spec.command(req.command_id)
        run_dir = req.platform_run_dir
        inv = build_invocation(self.spec, cmd, req.params, run_dir=run_dir)
        argv = list(inv["argv"])

        rt = self.spec.runtime or {}
        run_id_arg = rt.get("run_id_arg")
        if run_id_arg:
            argv += [run_id_arg, req.run_id]

        env = dict(os.environ)
        env.update({k: str(v) for k, v in inv["env"].items()})
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        # ⚠️ 不可直接印 `inv["redacted"]["cmdline"]` —— 那是**加上 run_id_arg 之前**
        #    的命令列。印錯會讓人以為旗標沒送出去而去查一個不存在的問題
        #    （2026-08-23 實際踩到：真正沒生效的是引擎那端，console 卻先誤導了一輪）。
        shown = list(inv["redacted"]["argv"])
        if run_id_arg:
            shown += [run_id_arg, req.run_id]
        rs.append_console(req.run_id, "$ " + " ".join(shlex.quote(str(t)) for t in shown))
        if req.remark:
            rs.append_console(req.run_id, "（備註：%s）" % req.remark)

        # 引擎自己開 run 目錄時，要能從「比啟動時間新」認出是哪一個
        started_at = time.time()
        console = open(rs.console_path(req.run_id), "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(argv, cwd=inv["cwd"], env=env,
                                stdout=console, stderr=subprocess.STDOUT)
        self._procs[req.run_id] = proc
        self._engine_dirs[req.run_id] = self._engine_run_dir(req.run_id) if run_id_arg else None
        threading.Thread(
            target=self._watch,
            args=(req.run_id, proc, console, started_at),
            daemon=True, name="cli-%s" % req.run_id).start()
        return RunHandle(run_id=req.run_id, pid=proc.pid)

    # ---- 背景盯梢（父程序是唯一寫入者）----
    def _watch(self, run_id, proc, console, started_at):
        """盯到程序結束。順便認出引擎的 run 目錄，並從 console 推進度。

        ⚠️ 只有這個 thread 會寫這個 run 的 status —— 與 `PytestAdapter` 同一條
        「單一寫入者」約束（`core/jsonio.py` 的鎖是 threading.Lock，跨程序無效）。
        """
        last_phase = None
        try:
            while True:
                if self._engine_dirs.get(run_id) is None:
                    d = _discover_engine_dir(self._runs_root(), started_at)
                    if d:
                        self._engine_dirs[run_id] = d
                        rs.append_console(run_id, "（引擎 run 目錄：%s）"
                                          % rel_to_repo(d))
                last_phase = self._pump_phase(run_id, last_phase)
                if proc.poll() is not None:
                    self._pump_phase(run_id, last_phase)   # 收尾再讀一次
                    break
                time.sleep(_POLL_SEC)
        finally:
            try:
                console.close()
            except OSError:
                pass
        self._finish(run_id, proc.returncode)

    def _runs_root(self) -> str | None:
        """引擎所有 run 目錄的**父目錄**（`artifacts.run_dir` 樣板去掉 `{run_id}`）。"""
        tpl = self._artifacts().get("run_dir")
        if not tpl or "{run_id}" not in tpl:
            return None
        return os.path.join(REPO_ROOT, os.path.dirname(tpl.replace("{run_id}", "x")))

    def _pump_phase(self, run_id, last_phase):
        """把引擎自己寫的階段同步到平台。

        走 tool.json 宣告的 `run.status_source`：

            {"kind": "tool_run_status",
             "path": "tools/CRUX_Performance/logs/runs/{run_id}/run_status.json",
             "phase_field": "phase"}

        ⭐ **不從 console 字串猜** —— 引擎已經把階段寫成欄位了，
        而字串比對會隨引擎的日誌措辭漂移。`run.phases` 也早就宣告了
        每個階段的中文 label 與 tone，直接對得上。
        """
        src = self._status_source()
        if not src:
            return last_phase
        path = self._engine_status_path(run_id)
        if not path or not os.path.isfile(path):
            return last_phase
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return last_phase                  # 引擎正在寫、讀到半截 —— 下一輪再試
        phase = data.get(src.get("phase_field") or "phase")
        if phase and phase != last_phase:
            self._phase(run_id, phase)
            return phase
        return last_phase

    def _status_source(self) -> dict | None:
        src = (self.spec.run or {}).get("status_source") or {}
        return src if src.get("kind") == "tool_run_status" and src.get("path") else None

    def _artifacts(self) -> dict:
        return (self.spec.raw or {}).get("artifacts") or {}

    def _engine_run_dir(self, run_id) -> str | None:
        """引擎自己的 run 目錄（絕對路徑）。

        樣板來自 `artifacts.run_dir`；`{run_id}` 填的是**引擎的** run_id ——
        宣告了 `runtime.run_id_arg` 的（CRUX／七星）就等於平台的，
        wbot 沒有，只能用 `_engine_dirs` 探測到的目錄名。
        """
        tpl = self._artifacts().get("run_dir")
        if not tpl:
            return None
        d = self._engine_dirs.get(run_id)
        eid = os.path.basename(d) if d else run_id
        return os.path.join(REPO_ROOT, tpl.replace("{run_id}", eid))

    def _engine_status_path(self, run_id) -> str | None:
        """引擎的 run_status.json 絕對路徑（`status_source.path` 的樣板）。"""
        src = self._status_source()
        if not src:
            return None
        d = self._engine_dirs.get(run_id)
        eid = os.path.basename(d) if d else run_id
        return os.path.join(REPO_ROOT, src["path"].replace("{run_id}", eid))

    def _phase(self, run_id, tool_phase, **extra):
        """更新工具階段，並在第一次看到工具階段時把**平台 phase** 推進到 `running`。

        ⚠️ 兩者是不同層次：`tool_phase` 是工具自己的階段（會員載入、關盤結算…），
        `phase` 是平台的生命週期（queued/starting/running/…）。
        `manager.start()` 只設到 `starting`，**沒有人負責推到 `running`** ——
        於是一輪跑 30 分鐘的壓測從頭到尾顯示「啟動中」，儀表板的
        「執行中 N」也算得不對（2026-08-23 實跑七星才看出來）。
        """
        pm = self.spec.phase_meta(tool_phase)
        cur = (rs.read_status(run_id) or {}).get("phase")
        if cur == "starting":
            extra.setdefault("phase", "running")
        rs.update_status(run_id, tool_phase=tool_phase, tool_phase_label=pm.get("label"),
                         tool_phase_tone=pm.get("tone"), **extra)

    def _finish(self, run_id, code):
        st = rs.read_status(run_id) or {}
        stopped = st.get("phase") == "stopping" or bool(st.get("stop_reason"))
        if stopped:
            phase = "stopped"
        elif code == 0:
            phase = "completed"
        else:
            phase = "failed"

        summary = {"kind": "cli", "exit_code": code}
        if phase == "failed":
            summary["note"] = ("引擎以退出碼 %s 結束 —— 先看 console 的 stderr；"
                               "壓測最常見的是前置條件不成立（期數未開盤、"
                               "master_url 過期），不是平台問題。" % code)
        self._phase(run_id, "generating_reports")
        artifacts = [a.to_dict() for a in self.reports(run_id)]
        rs.update_status(run_id, phase=phase, exit_code=code, summary=summary,
                         artifacts=artifacts, tool_phase=phase,
                         tool_phase_label={"completed": "完成", "failed": "失敗",
                                           "stopped": "已停止"}[phase],
                         tool_phase_tone={"completed": "success", "failed": "danger",
                                          "stopped": "warn"}[phase])
        # ⛔ 同 pytest_.py：不釋放併發佔位的話，第一次跑完之後這支工具
        #    就再也啟動不了（2026-08-23 情境 B 走查）。
        try:
            from runner import manager as _mgr
            _mgr.on_finished(run_id)
        except Exception:                  # noqa: BLE001
            pass
        self._procs.pop(run_id, None)

    # ---- 停止：兩種策略 ----
    def stop(self, run_id: str, *, force: bool = False, reason: str = "user") -> dict:
        """依 `stop.strategy` 停止。

        | strategy | 做法 | 為什麼 |
        | --- | --- | --- |
        | `tree`（預設） | 直接殺整棵程序樹 | CRUX／七星的 locust worker 是子程序 |
        | `flag` | **先寫 `stop.flag`**，等 `grace_seconds`，逾時才殺 | wbot 要讓 worker 優雅收尾並產出報告；<br>且它的**孫程序握著 WebSocket**，直接 terminate 殺不掉、會繼續下注 |

        `force=True` 一律跳過寬限直接殺。
        """
        stop_spec = self.spec.stop or {}
        strategy = stop_spec.get("strategy") or "tree"
        rs.update_status(run_id, phase="stopping", stop_reason=reason)
        proc = self._procs.get(run_id)

        if strategy == "flag" and not force:
            flag_name = stop_spec.get("flag_file") or "stop.flag"
            d = self._engine_dirs.get(run_id)
            if d and os.path.isdir(d):
                try:
                    with open(os.path.join(d, flag_name), "w", encoding="utf-8") as f:
                        f.write(reason)
                    rs.append_console(run_id, "（已寫 %s，等 worker 優雅收尾）" % flag_name)
                except OSError as e:
                    rs.append_console(run_id, "（寫 %s 失敗：%s，改為強制終止）" % (flag_name, e))
            else:
                rs.append_console(run_id, "（找不到引擎 run 目錄，%s 無處可寫，改為強制終止）"
                                  % flag_name)
                d = None
            if d:
                grace = int(stop_spec.get("grace_seconds") or 30)
                deadline = time.time() + grace
                while time.time() < deadline:
                    if not proc or proc.poll() is not None:
                        return rs.read_status(run_id) or {"run_id": run_id}
                    time.sleep(0.5)
                rs.append_console(run_id, "（寬限 %d 秒已過，強制終止）" % grace)

        if proc and proc.poll() is None:
            _kill_tree(proc.pid, force=True)
        return rs.read_status(run_id) or {"run_id": run_id}

    def status(self, run_id: str) -> dict:
        return rs.read_status(run_id) or {"run_id": run_id}

    def logs(self, run_id: str, offset: int = 0, limit_bytes: int = 262144) -> dict:
        return rs.tail_console(run_id, offset=offset, limit_bytes=limit_bytes)

    def reports(self, run_id: str) -> list[ArtifactRef]:
        """平台的 console ＋ `artifacts.primary` 宣告的引擎報告。

        ⚠️ 引擎的報告在**它自己的** run 目錄，不在平台的 —— 這就是為什麼
        `runtime.run_id_arg` 重要：兩邊的 run_id 對不上就找不到報告。
        只列**實際存在**的檔（壓測中途停止時多數報告不會產出）。
        """
        out = [ArtifactRef(key="console", label="執行輸出",
                           href="/reports/%s/console.log" % run_id, kind="text")]
        d = self._engine_run_dir(run_id)
        if not d or not os.path.isdir(d):
            return out
        rel = rel_to_repo(d)
        whitelist = set(self._artifacts().get("whitelist") or [])
        for i, r in enumerate(self._artifacts().get("primary") or []):
            fn = r.get("file")
            if not fn or not os.path.isfile(os.path.join(d, fn)):
                continue
            if whitelist and fn not in whitelist:
                continue                     # 白名單是對外開放的界線，不在名單上就不給連結
            out.append(ArtifactRef(
                key=fn, label=r.get("label") or fn,
                href="/files/%s/%s" % (rel, fn),
                kind=r.get("kind") or "html",
                open=r.get("open") or "newtab",
                primary=(i == 0)))
        return out

    # ---- 同步命令 ----
    def run_command(self, command: dict, params: dict) -> dict:
        inv = build_invocation(self.spec, command, params)
        argv = list(inv["argv"])
        json_flag = (self.spec.runtime or {}).get("json_flag")
        if json_flag:
            argv.append(json_flag)
        env = dict(os.environ)
        env.update({k: str(v) for k, v in inv["env"].items()})
        timeout = float(command.get("timeout_sec") or 120)
        started = time.time()
        cwd = inv["cwd"]
        if not os.path.isdir(cwd):
            return {"ok": False, "error": f"工作目錄不存在：{cwd}",
                    "result": {"kind": "text", "text": f"工作目錄不存在：{cwd}"}}
        try:
            proc = subprocess.run(argv, cwd=cwd, env=env, timeout=timeout,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            return {"ok": False, "error": f"執行檔找不到：{e}",
                    "result": {"kind": "text", "text": str(e)}}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"逾時（{timeout:.0f} 秒）",
                    "result": {"kind": "text", "text": f"執行超過 {timeout:.0f} 秒被中止。"}}

        result = _parse_stdout(proc.stdout, command)
        if result is None:
            txt = (proc.stdout or "") or (proc.stderr or "")
            result = {"kind": "text", "text": txt[:_MAX_TEXT] or "（無輸出）"}
        # 退出碼非 0 未必是壞事：verify 有失敗筆數時回 1，結果表本身才是要看的東西
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "elapsed_ms": int((time.time() - started) * 1000),
            "result": result,
            "cmdline": inv["redacted"]["cmdline"],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }


def _discover_engine_dir(root, started_at):
    """認出引擎在本次啟動後新開的 run 目錄。

    ⚠️ 只給**沒有宣告 `runtime.run_id_arg`** 的工具用（wbot 的 `run_perf.py`
    沒開 `--run-id`）。有宣告的一律直接對上平台的 run_id，不走這條 ——
    探測終究是猜的，**同時有兩個 run 在跑就可能認錯**。

    → 正解是替 `run_perf.py` 的 `build_body()` 補 `--run-id`
      （`run_params` 的 dataclass 早就有 `run_id` 欄位，只差 CLI 沒開口）。
    """
    if not root or not os.path.isdir(root):
        return None
    best, best_t = None, started_at - 2      # 容忍 2 秒時鐘誤差
    try:
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            mt = os.path.getmtime(p)
            if mt >= best_t:
                best, best_t = p, mt
    except OSError:
        return None
    return best


def _kill_tree(pid, force=False):
    """殺整棵程序樹。

    ⚠️ 壓測引擎會起 locust worker／asyncio 子程序，**孫程序握著 WebSocket** ——
    只殺父程序的話它們會留下來繼續下注（真金流）。
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


def _exe_of(spec) -> str:
    from adapters.argv import resolve_exe
    return resolve_exe(spec)


def _cwd_of(spec) -> str:
    from adapters.argv import resolve_cwd
    return resolve_cwd(spec)


def _parse_stdout(out: str, command: dict) -> dict | None:
    """從最後一行往前找第一個解析得出的 JSON 物件（stdout 可能混著雜訊）。"""
    for line in reversed([ln.strip() for ln in (out or "").splitlines() if ln.strip()]):
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        # 腳本自己宣告的 kind 優先（它最清楚這次吐的是什麼形狀），沒宣告才用 registry 的
        obj.setdefault("kind", (command.get("result") or {}).get("kind", "text"))
        return obj
    return None
