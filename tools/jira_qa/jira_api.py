# -*- coding: utf-8 -*-
"""JIRA 唯讀查詢工具（Jira Server 8.6.1 / REST API v2）

用途：讀取 JIRA 單的內容供「修復重驗」使用 —— 取單、JQL 查詢、下載附件（截圖／log）。
      本工具**只讀不寫**：不開單、不留言、不改狀態、不關單。開單與關單一律由使用者手動執行。

使用方式（CLI）：
    python tools\\jira_qa\\jira_api.py --check                      # 連線與認證檢查
    python tools\\jira_qa\\jira_api.py BOT-799                      # 印出單子內容（純文字）
    python tools\\jira_qa\\jira_api.py BOT-799 --changelog          # 併印狀態異動歷程
    python tools\\jira_qa\\jira_api.py BOT-799 --json               # 印出正規化 JSON
    python tools\\jira_qa\\jira_api.py BOT-799 --attachments --out <目錄>
    python tools\\jira_qa\\jira_api.py --jql "project = BOT AND status = Resolved" --max 20

使用方式（Python）：
    from jira_qa.jira_api import JiraClient
    issue = JiraClient.from_config().get_issue("BOT-799")
    print(issue.to_text())

前置條件：
  1. 需在**公司內網**（站台為 on-prem，外網不通）。
  2. `config/config.local.json`（不版控）需有 `jira.username` / `jira.password`；
     `jira.base_url` 預設取自 `config/environments.json`。
     ⚠️ Jira Server 8.6.1 早於 PAT（Personal Access Token 自 8.14 起才支援），
     因此只能用**帳號密碼 Basic Auth**。
  3. ⚠️ 連續認證失敗會觸發 Jira 的 CAPTCHA 鎖定，屆時**密碼正確也會回 401**，
     須先用瀏覽器登入該站台通過驗證碼才會解除（本工具會辨識並提示）。

附件落點：依 CLAUDE.md §8.5，附件一律下載到 scratchpad／系統暫存，**不落 repo**。
"""

import argparse
import base64
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_TIMEOUT = 20

# 取單時要求的欄位（限縮 payload；需要更多欄位時在此加）
ISSUE_FIELDS = (
    "summary,description,status,resolution,issuetype,priority,reporter,assignee,"
    "created,updated,resolutiondate,fixVersions,versions,labels,components,"
    "comment,attachment,issuelinks,environment"
)
# JQL 查詢用的輕量欄位（不含 description/comment/attachment）
SEARCH_FIELDS = (
    "summary,status,resolution,issuetype,priority,assignee,reporter,"
    "created,updated,resolutiondate,fixVersions,labels,components"
)


class JiraError(RuntimeError):
    """JIRA 存取失敗（連線、認證、權限、單號不存在）。"""


# --- 設定載入（與 crux_qa.config_loader 同慣例：environments.json + config.local.json 深度合併） ---


def _deep_merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config():
    with open(CONFIG_DIR / "environments.json", encoding="utf-8") as f:
        config = json.load(f)
    local_path = CONFIG_DIR / "config.local.json"
    if local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            config = _deep_merge(config, json.load(f))
    return config


def _get(node, *path, default=None):
    """安全取巢狀值：_get(d, 'fields', 'status', 'name')"""
    cur = node
    for key in path:
        if not isinstance(cur, dict) or cur.get(key) is None:
            return default
        cur = cur[key]
    return cur


def _names(items, key="name"):
    return [i.get(key, "") for i in (items or []) if isinstance(i, dict)]


# --- 資料模型 ---


@dataclass
class JiraIssue:
    """正規化後的 JIRA 單（唯讀快照）。"""

    key: str
    url: str
    summary: str = ""
    description: str = ""
    environment: str = ""
    status: str = ""
    resolution: str = ""
    issue_type: str = ""
    priority: str = ""
    reporter: str = ""
    assignee: str = ""
    created: str = ""
    updated: str = ""
    resolved: str = ""
    fix_versions: list = field(default_factory=list)
    affects_versions: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    components: list = field(default_factory=list)
    comments: list = field(default_factory=list)  # [{author, created, body}]
    attachments: list = field(default_factory=list)  # [{filename, size, mime, created, url}]
    links: list = field(default_factory=list)  # [{type, key, summary, status}]
    status_history: list = field(default_factory=list)  # [{when, who, from, to}]

    def to_dict(self):
        return asdict(self)

    def to_text(self):
        """轉為人／模型可讀的純文字摘要（供重驗時直接閱讀）。"""
        lines = [
            f"# {self.key} {self.summary}",
            f"連結：{self.url}",
            "",
            f"狀態：{self.status}"
            + (f"／解決：{self.resolution}" if self.resolution else "")
            + f"　類型：{self.issue_type}　優先級：{self.priority}",
            f"回報人：{self.reporter}　指派：{self.assignee}",
            f"建立：{self.created}　更新：{self.updated}"
            + (f"　解決於：{self.resolved}" if self.resolved else ""),
        ]
        if self.fix_versions:
            lines.append(f"修復版本（fixVersions）：{'、'.join(self.fix_versions)}")
        if self.affects_versions:
            lines.append(f"影響版本：{'、'.join(self.affects_versions)}")
        if self.components:
            lines.append(f"模組：{'、'.join(self.components)}")
        if self.labels:
            lines.append(f"標籤：{'、'.join(self.labels)}")
        if self.links:
            lines.append("關聯單：")
            for l in self.links:
                lines.append(f"  - {l['type']} {l['key']}（{l['status']}）{l['summary']}")

        lines += ["", "## 內容（description）", self.description or "（空白）"]
        if self.environment:
            lines += ["", "## 環境（environment 欄位）", self.environment]

        if self.status_history:
            lines += ["", "## 狀態異動歷程"]
            for h in self.status_history:
                lines.append(f"  - {h['when']} {h['who']}：{h['from']} → {h['to']}")

        if self.attachments:
            lines += ["", f"## 附件（{len(self.attachments)}）"]
            for a in self.attachments:
                lines.append(
                    f"  - {a['filename']}（{a['mime']}, {a['size']} bytes, {a['created']}）"
                )

        if self.comments:
            lines += ["", f"## 留言（{len(self.comments)}）"]
            for c in self.comments:
                lines += [f"--- {c['created']} {c['author']} ---", c["body"], ""]

        return "\n".join(lines)


# --- Client ---


class JiraClient:
    """JIRA REST API v2 唯讀 client（Basic Auth）。"""

    def __init__(self, base_url, username, password, timeout=DEFAULT_TIMEOUT, session_cookie=""):
        if not base_url:
            raise JiraError("缺少 jira.base_url（請確認 config/environments.json）")
        if not username or not password:
            raise JiraError(
                "缺少 JIRA 帳密：請在 config/config.local.json 補上\n"
                '  {"jira": {"username": "<帳號>", "password": "<密碼>"}}\n'
                "（該檔不版控；範本見 config/config.example.json）"
            )
        self.base_url = base_url.rstrip("/")
        self._auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.timeout = timeout
        # 已通過 2FA 的瀏覽器 session（JSESSIONID=xxx），僅附件下載需要，見 download_attachments
        self.session_cookie = (session_cookie or "").strip()

    @classmethod
    def from_config(cls, timeout=DEFAULT_TIMEOUT):
        node = _load_config().get("jira") or {}
        return cls(
            node.get("base_url", ""),
            node.get("username", ""),
            node.get("password", ""),
            timeout=timeout,
            session_cookie=node.get("session_cookie", ""),
        )

    # -- 底層 --

    def _open(self, url):
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {self._auth}")
        req.add_header("Accept", "application/json")
        # Jira Server 對「非瀏覽器」的 basic auth 不套 CAPTCHA cookie 流程，但仍需帶 UA
        req.add_header("User-Agent", "jira_qa-readonly/1.0")
        if self.session_cookie:
            req.add_header("Cookie", self.session_cookie)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise JiraError(self._explain_http_error(e, url)) from None
        except urllib.error.URLError as e:
            raise JiraError(
                f"無法連線 JIRA（{self.base_url}）：{e.reason}\n"
                "本站台為公司內網 on-prem，請確認已連上內網／VPN。"
            ) from None

    @staticmethod
    def _explain_http_error(e, url):
        denied = e.headers.get("X-Authentication-Denied-Reason", "") if e.headers else ""
        if e.code == 401:
            msg = f"JIRA 認證失敗（401）：{url}"
            if "CAPTCHA" in denied.upper():
                msg += (
                    "\n⚠️ 帳號已被 CAPTCHA 鎖定（連續登入失敗所致）——此時**密碼正確也會 401**。"
                    "\n   解法：用瀏覽器登入該 JIRA 站台、通過驗證碼後，本工具才會恢復。"
                )
            else:
                msg += "\n請確認 config/config.local.json 的 jira.username / jira.password 正確。"
            return msg
        if e.code == 403:
            return f"JIRA 拒絕存取（403）：{url}\n帳號可能無此專案／單子的瀏覽權限。"
        if e.code == 404:
            return f"JIRA 查無此資源（404）：{url}\n單號可能不存在，或帳號無該專案瀏覽權限（Jira 會以 404 隱藏）。"
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        return f"JIRA 回應錯誤（HTTP {e.code}）：{url}\n{body}"

    def _api(self, path, params=None):
        url = f"{self.base_url}/rest/api/2/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with self._open(url) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # -- 對外方法（全部唯讀） --

    def check(self):
        """連線與認證檢查，回傳 {server, version, user}。"""
        info = self._api("serverInfo")
        me = self._api("myself")
        return {
            "server": info.get("serverTitle", ""),
            "base_url": info.get("baseUrl", ""),
            "version": info.get("version", ""),
            "deployment": info.get("deploymentType", ""),
            "user": me.get("displayName") or me.get("name", ""),
            "email": me.get("emailAddress", ""),
        }

    def get_issue(self, key, changelog=False):
        """取單並正規化為 JiraIssue。changelog=True 時併帶狀態異動歷程。"""
        key = key.strip().upper()
        params = {"fields": ISSUE_FIELDS}
        if changelog:
            params["expand"] = "changelog"
        raw = self._api(f"issue/{urllib.parse.quote(key)}", params)
        return self._to_issue(raw, changelog=changelog)

    def search(self, jql, max_results=50):
        """JQL 查詢，回傳輕量 JiraIssue 清單（無 description／留言／附件）。"""
        raw = self._api(
            "search",
            {"jql": jql, "maxResults": max_results, "fields": SEARCH_FIELDS},
        )
        return [self._to_issue(i) for i in raw.get("issues", [])]

    def download_attachments(self, issue, out_dir):
        """下載單子附件到 out_dir（截圖／log）。回傳已下載的路徑清單。

        ⚠️ out_dir 請指向 scratchpad／系統暫存，不要落在 repo 內（CLAUDE.md §8.5）。
        ⚠️ 本站台裝有 2FA 外掛：附件走 `/secure/attachment/` 的 **web 層**（非 REST），
           Basic Auth 會被 2FA 攔截並回傳登入頁 HTML。本方法偵測到即中止並提示，
           **不會**把 HTML 當成圖片寫入檔案（避免產出看似正常實為壞檔的 .png）。
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        saved = []
        for a in issue.attachments:
            name = re.sub(r'[\\/:*?"<>|]', "_", a["filename"]) or "attachment"
            dest = out / name
            with self._open(a["url"]) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read()
            if self._looks_like_login_page(ctype, data, a.get("mime", "")):
                hint = (
                    "已設定 session_cookie 但仍被擋 —— cookie 可能已過期，請重新從瀏覽器複製。"
                    if self.session_cookie
                    else
                    "解法二選一：\n"
                    "  (a) 在 config/config.local.json 的 jira 區塊加上已通過 2FA 的瀏覽器 session：\n"
                    '      "session_cookie": "JSESSIONID=<從瀏覽器開發者工具複製>"\n'
                    "      （該 cookie 會過期，失效時重新複製即可）\n"
                    f"  (b) 用瀏覽器開 {issue.url} 自行下載，再把檔案路徑交給我閱讀。"
                )
                raise JiraError(
                    f"附件下載被擋（{a['filename']}）：伺服器回傳的是登入／2FA 驗證頁，不是檔案內容。\n"
                    "原因：附件端點 /secure/attachment/ 走 web 層，本站台的 2FA 外掛不接受 Basic Auth。\n"
                    + hint
                )
            dest.write_bytes(data)
            saved.append(dest)
        return saved

    @staticmethod
    def _looks_like_login_page(content_type, data, expected_mime):
        """回應是否為登入／2FA 頁面（而非預期的附件內容）。"""
        if "html" in expected_mime.lower():
            return False  # 附件本身就是 HTML，無從分辨，放行
        if "text/html" in content_type:
            return True
        return data.lstrip()[:100].lower().startswith(b"<!doctype html")

    # -- 正規化 --

    def _to_issue(self, raw, changelog=False):
        f = raw.get("fields") or {}
        key = raw.get("key", "")
        issue = JiraIssue(
            key=key,
            url=f"{self.base_url}/browse/{key}",
            summary=f.get("summary") or "",
            description=f.get("description") or "",
            environment=f.get("environment") or "",
            status=_get(f, "status", "name", default=""),
            resolution=_get(f, "resolution", "name", default=""),
            issue_type=_get(f, "issuetype", "name", default=""),
            priority=_get(f, "priority", "name", default=""),
            reporter=_get(f, "reporter", "displayName", default=""),
            assignee=_get(f, "assignee", "displayName", default="（未指派）"),
            created=f.get("created") or "",
            updated=f.get("updated") or "",
            resolved=f.get("resolutiondate") or "",
            fix_versions=_names(f.get("fixVersions")),
            affects_versions=_names(f.get("versions")),
            labels=list(f.get("labels") or []),
            components=_names(f.get("components")),
        )
        for c in _get(f, "comment", "comments", default=[]) or []:
            issue.comments.append(
                {
                    "author": _get(c, "author", "displayName", default=""),
                    "created": c.get("created", ""),
                    "body": c.get("body", ""),
                }
            )
        for a in f.get("attachment") or []:
            issue.attachments.append(
                {
                    "filename": a.get("filename", ""),
                    "size": a.get("size", 0),
                    "mime": a.get("mimeType", ""),
                    "created": a.get("created", ""),
                    "url": a.get("content", ""),
                }
            )
        for l in f.get("issuelinks") or []:
            if l.get("outwardIssue"):
                rel, other = _get(l, "type", "outward", default="關聯"), l["outwardIssue"]
            elif l.get("inwardIssue"):
                rel, other = _get(l, "type", "inward", default="關聯"), l["inwardIssue"]
            else:
                continue
            issue.links.append(
                {
                    "type": rel,
                    "key": other.get("key", ""),
                    "summary": _get(other, "fields", "summary", default=""),
                    "status": _get(other, "fields", "status", "name", default=""),
                }
            )
        if changelog:
            for h in _get(raw, "changelog", "histories", default=[]) or []:
                for item in h.get("items") or []:
                    if item.get("field") == "status":
                        issue.status_history.append(
                            {
                                "when": h.get("created", ""),
                                "who": _get(h, "author", "displayName", default=""),
                                "from": item.get("fromString", ""),
                                "to": item.get("toString", ""),
                            }
                        )
        return issue


# --- CLI ---


def main(argv=None):
    p = argparse.ArgumentParser(description="JIRA 唯讀查詢（取單／JQL／附件）")
    p.add_argument("key", nargs="?", help="單號，如 BOT-799")
    p.add_argument("--check", action="store_true", help="連線與認證檢查")
    p.add_argument("--jql", help="以 JQL 查詢單子清單")
    p.add_argument("--max", type=int, default=50, help="JQL 最大筆數（預設 50）")
    p.add_argument("--changelog", action="store_true", help="併帶狀態異動歷程")
    p.add_argument("--json", action="store_true", help="輸出正規化 JSON")
    p.add_argument("--attachments", action="store_true", help="下載附件")
    p.add_argument("--out", help="附件輸出目錄（預設系統暫存；勿指向 repo 內）")
    args = p.parse_args(argv)

    try:
        client = JiraClient.from_config()

        if args.check:
            info = client.check()
            print(
                f"✅ 連線正常\n"
                f"   站台：{info['server']}（{info['base_url']}）\n"
                f"   版本：Jira {info['version']} / {info['deployment']}\n"
                f"   登入身分：{info['user']} {info['email']}"
            )
            return 0

        if args.jql:
            issues = client.search(args.jql, args.max)
            if args.json:
                print(json.dumps([i.to_dict() for i in issues], ensure_ascii=False, indent=2))
            else:
                print(f"共 {len(issues)} 筆：")
                for i in issues:
                    fv = f" fix={'/'.join(i.fix_versions)}" if i.fix_versions else ""
                    print(f"  {i.key:<12} [{i.status}]{fv}  {i.summary}")
            return 0

        if not args.key:
            p.error("需提供單號，或使用 --jql / --check")

        issue = client.get_issue(args.key, changelog=args.changelog)
        if args.json:
            print(json.dumps(issue.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(issue.to_text())

        if args.attachments:
            out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "jira_qa" / issue.key
            saved = client.download_attachments(issue, out)
            print(f"\n附件已下載 {len(saved)} 個 → {out}")
            for s in saved:
                print(f"  {s}")
        return 0

    except JiraError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
