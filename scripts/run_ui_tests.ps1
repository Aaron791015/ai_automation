# 用途：一鍵執行 UI 測試並產出 allure report
# 使用方式：powershell -File scripts\run_ui_tests.ps1 [-Headed] [-Filter <-k 表達式>] [-Marker <-m 表達式>] [-SkipReport] [-Open]
# 前置條件：先執行 scripts\setup_test_env.ps1 完成環境建置
param(
    [switch]$Headed,      # 顯示瀏覽器視窗
    [string]$Filter,      # pytest -k 篩選
    [string]$Marker,      # pytest -m 篩選（smoke / write_action）
    [switch]$SkipReport,  # 不產 allure report
    [switch]$Open         # 產出後開啟報告
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$resultsDir = Join-Path $repoRoot "reports\allure-results"
$reportDir = Join-Path $repoRoot "reports\allure-report"

if (-not (Test-Path $venvPython)) {
    Write-Error "找不到 .venv，請先執行 scripts\setup_test_env.ps1"
    exit 1
}

# 清空上次結果，確保報告只含本次執行
if (Test-Path $resultsDir) { Remove-Item -Recurse -Force $resultsDir }

$pytestArgs = @("-m", "pytest", "-v")
if ($Headed) { $pytestArgs += "--headed" }
if ($Filter) { $pytestArgs += @("-k", $Filter) }
if ($Marker) { $pytestArgs += @("-m", $Marker) }

Push-Location $repoRoot
& $venvPython @pytestArgs
$pytestExit = $LASTEXITCODE
Pop-Location

if (-not $SkipReport) {
    # 取 allure CLI：npm 全域版優先（避免 PATH 上的舊版 2.7.0）
    $allureCmd = $null
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        $npmAllure = Join-Path ((npm prefix -g).Trim()) "allure.cmd"
        if (Test-Path $npmAllure) { $allureCmd = $npmAllure }
    }
    if (-not $allureCmd) {
        $found = Get-Command allure -ErrorAction SilentlyContinue
        if ($found) { $allureCmd = $found.Source }
    }
    if ($allureCmd) {
        & $allureCmd generate $resultsDir -o $reportDir --clean
        Write-Host "allure report：$reportDir\index.html"
        if ($Open) { & $allureCmd open $reportDir }
    } else {
        Write-Warning "找不到 allure CLI，略過報告產出（請執行 setup_test_env.ps1）"
    }
}

exit $pytestExit
