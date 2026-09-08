param(
    [string]$PythonPath = ".\.venv\Scripts\python.exe",
    [int]$DailyLimit = 5,
    [switch]$EnableTradingAgents,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$python = [IO.Path]::GetFullPath((Join-Path $workspace $PythonPath))

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable not found: $python"
}
if ($DailyLimit -lt 1 -or $DailyLimit -gt 50) {
    throw "DailyLimit must be between 1 and 50"
}

$shadowName = "InvestmentAgent-ShadowDaily"
$evaluateName = "InvestmentAgent-Evaluate"
$portfolioName = "InvestmentAgent-PortfolioShadow"
$shadowArgs = "-m investment_agent.trading.decision.shadow_daily --limit $DailyLimit"
$portfolioArgs = "-m investment_agent.trading.decision.portfolio_shadow --limit $DailyLimit"
$evaluateArgs = "-m investment_agent.research.commands.evaluate"

Write-Output "Workspace: $workspace"
Write-Output "Python: $python"
Write-Output "${shadowName}: Tue-Sat 08:00 KST, limit=$DailyLimit"
Write-Output "${evaluateName}: daily 08:30 KST"
if ($EnableTradingAgents) {
    Write-Output "${portfolioName}: Tue-Sat 08:15 KST, limit=$DailyLimit"
}

if (-not $Apply) {
    Write-Output "Preview only. Re-run with -Apply after .env model settings are ready."
    exit 0
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$shadowAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $shadowArgs `
    -WorkingDirectory $workspace
$shadowTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Tuesday,Wednesday,Thursday,Friday,Saturday `
    -At 8:00AM
Register-ScheduledTask `
    -TaskName $shadowName `
    -Action $shadowAction `
    -Trigger $shadowTrigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

if ($EnableTradingAgents) {
    $portfolioAction = New-ScheduledTaskAction `
        -Execute $python `
        -Argument $portfolioArgs `
        -WorkingDirectory $workspace
    $portfolioTrigger = New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Tuesday,Wednesday,Thursday,Friday,Saturday `
        -At 8:15AM
    Register-ScheduledTask `
        -TaskName $portfolioName `
        -Action $portfolioAction `
        -Trigger $portfolioTrigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
}

$evaluateAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $evaluateArgs `
    -WorkingDirectory $workspace
$evaluateTrigger = New-ScheduledTaskTrigger -Daily -At 8:30AM
Register-ScheduledTask `
    -TaskName $evaluateName `
    -Action $evaluateAction `
    -Trigger $evaluateTrigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Output "Registered $shadowName and $evaluateName."
if ($EnableTradingAgents) {
    Write-Output "Registered $portfolioName."
}
