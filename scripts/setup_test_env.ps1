# 用途：建置/檢查 UI 測試環境（冪等，可重複執行）
# 使用方式：powershell -File scripts\setup_test_env.ps1
# 前置條件：本機已安裝 **Python 3.11+ 與 Node.js 18+**（兩個都是必裝）。
#   ⛔ Node.js 不是選配 —— Playwright MCP 靠 `npx @playwright/mcp` 起，
#      沒有它就沒有瀏覽器，而探索／需求驗證／JIRA 重驗／開單複現全都要瀏覽器。
#      症狀還很難查：MCP 起不來時 session 只會安靜地少掉那些工具。
# 步驟：venv → pip 相依 → playwright chromium → allure CLI 檢查/升級 → 測試站連通性 → 總結

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$results = New-Object System.Collections.ArrayList

function Add-Result([string]$Item, [bool]$Ok, [string]$Detail) {
    [void]$results.Add([pscustomobject]@{ 項目 = $Item; 狀態 = $(if ($Ok) { "OK" } else { "FAIL" }); 說明 = $Detail })
}

# --- 1. Python 版本 ---
$pythonOk = $false
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd) {
    $pyVer = (python --version) -replace "Python ", ""
    if ([version]$pyVer -ge [version]"3.11") { $pythonOk = $true }
    Add-Result "Python" $pythonOk "版本 $pyVer（需 >= 3.11）"
} else {
    Add-Result "Python" $false "找不到 python，請先安裝 Python 3.11+"
}

# --- 1b. Node.js（必裝，不是選配）---
# ⛔ Playwright MCP 靠 `npx @playwright/mcp` 起 —— 沒有 Node 就沒有瀏覽器，
#    而探索／需求驗證／JIRA 重驗／開單複現全都要瀏覽器。
#    缺它的症狀**很難查**：MCP server 起不來，session 只會安靜地少掉那幾個工具。
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeVer = (node -v) 2>$null
    $nodeMajor = 0
    if ($nodeVer -match "v(\d+)") { $nodeMajor = [int]$Matches[1] }
    Add-Result "Node.js" ($nodeMajor -ge 18) "版本 $nodeVer（需 >= 18；Playwright MCP 與 allure CLI 都靠它）"
} else {
    Add-Result "Node.js" $false "找不到 node —— 請安裝 Node.js 18+。⛔ 沒有它就沒有瀏覽器自動化（Playwright MCP）"
}

if (-not $pythonOk) { $results | Format-Table -AutoSize; exit 1 }

# --- 2. venv ---
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "建立虛擬環境 .venv ..."
    python -m venv (Join-Path $repoRoot ".venv")
}
Add-Result "venv" (Test-Path $venvPython) $venvPython

# --- 3. pip 相依 ---
Write-Host "安裝 requirements.txt 相依套件 ..."
& $venvPython -m pip install -q -r (Join-Path $repoRoot "requirements.txt")
Add-Result "pip 相依" ($LASTEXITCODE -eq 0) "requirements.txt（exit=$LASTEXITCODE）"

# 統一測試平台能不能啟動 —— 相依漏裝時錯誤訊息是 ModuleNotFoundError，
# 看不出是環境建置的問題，所以在這裡先攔一次（2026-08-23）。
& $venvPython -c "import flask, psutil, requests" 2>$null
Add-Result "測試平台相依" ($LASTEXITCODE -eq 0) `
    $(if ($LASTEXITCODE -eq 0) { "flask/psutil/requests 就緒 → tools\test_platform\run_server.bat" }
      else { "缺 flask/psutil/requests —— 這三個列在根 requirements.txt，重跑本腳本或手動 pip install" })

# --- 4. playwright chromium ---
Write-Host "安裝 playwright chromium（已存在則跳過）..."
& $venvPython -m playwright install chromium
Add-Result "playwright chromium" ($LASTEXITCODE -eq 0) "exit=$LASTEXITCODE"

# --- 5. allure CLI（需 >= 2.24，優先 npm 全域安裝）---
function Get-AllureCmd {
    # 優先取 npm 全域安裝的 allure（避免 PATH 上的舊版 2.7.0 蓋過）
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        $npmPrefix = (npm prefix -g).Trim()
        $npmAllure = Join-Path $npmPrefix "allure.cmd"
        if (Test-Path $npmAllure) { return $npmAllure }
    }
    $pathAllure = Get-Command allure -ErrorAction SilentlyContinue
    if ($pathAllure) { return $pathAllure.Source }
    return $null
}

function Get-AllureVersion([string]$Cmd) {
    if (-not $Cmd) { return $null }
    try { return [version]((& $Cmd --version | Select-Object -First 1).Trim()) } catch { return $null }
}

$allureCmd = Get-AllureCmd
$allureVer = Get-AllureVersion $allureCmd
if (-not $allureVer -or $allureVer -lt [version]"2.24") {
    Write-Host "allure CLI 缺少或過舊（目前：$allureVer），以 npm 全域安裝新版 ..."
    npm install -g allure-commandline
    $allureCmd = Get-AllureCmd
    $allureVer = Get-AllureVersion $allureCmd
}
Add-Result "allure CLI" ($allureVer -and $allureVer -ge [version]"2.24") "版本 $allureVer（$allureCmd）"

# --- 6. 測試站連通性 ---
# ⛔ 網址**不寫在這裡** —— 本腳本是通用層，寫死任何產品的站台，
#    同事拿到範本就會看到他沒聽過的站台、且必然 FAIL（2026-08-23 範本驗收發現）。
#    要檢查哪些站台，在 config/environments.json 的 connectivity_check 宣告：
#        "connectivity_check": [ { "name": "<顯示名>", "url": "http://..." } ]
$envJson = Join-Path $repoRoot "config\environments.json"
$sites = @()
if (Test-Path $envJson) {
    try {
        $cfg = Get-Content $envJson -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.connectivity_check) { $sites = @($cfg.connectivity_check) }
    } catch {
        Add-Result "測試站連通性" $false "config\environments.json 解析失敗：$($_.Exception.Message)"
    }
}
if ($sites.Count -eq 0) {
    Write-Host "（未宣告要檢查的測試站，略過連通性檢查）"
    Write-Host "  要檢查的話，在 config\environments.json 加 connectivity_check：[{ name, url }]"
} else {
    foreach ($site in $sites) {
        try {
            $resp = Invoke-WebRequest -Uri $site.url -UseBasicParsing -TimeoutSec 10
            Add-Result $site.name $true "HTTP $($resp.StatusCode) $($site.url)"
        } catch {
            Add-Result $site.name $false "$($site.url) 無法連線（需內網環境）：$($_.Exception.Message)"
        }
    }
}

# --- 7. 總結 ---
Write-Host ""
Write-Host "=== 環境檢查總結 ==="
$results | Format-Table -AutoSize
if (($results | Where-Object { $_.狀態 -eq "FAIL" }).Count -gt 0) { exit 1 } else { exit 0 }
