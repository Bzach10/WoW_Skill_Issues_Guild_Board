# Registers the weekly cast-art refresh (scripts/weekly_cast_refresh.py) as
# a local Windows Task Scheduler job. This is a ONE-TIME, OPT-IN setup step
# — it does not run automatically and nothing in this repo calls it for you.
#
# Why local Task Scheduler and not GitHub Actions: the refresh regenerates
# art through ComfyUI on this machine's GPU, and GitHub Actions runners have
# no GPU. ComfyUI Desktop must already be running (or auto-launch) on this
# machine for the scheduled run to do anything.
#
# The day/time below are placeholders — do NOT treat them as decided.
# Confirm the actual day/time with Zach, then edit -DayOfWeek / -At (or pass
# them as parameters) before running this script.
#
# Usage (run from an elevated or normal PowerShell prompt — no admin rights
# needed for a per-user scheduled task):
#   .\scripts\setup_cast_refresh_task.ps1 -DayOfWeek Sunday -At 03:00

param(
    [string]$DayOfWeek = "Sunday",
    [string]$At = "03:00",
    [string]$TaskName = "WoWGuildBoard-WeeklyCastRefresh"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $RepoRoot "scripts\weekly_cast_refresh.py"
$PythonExe = (Get-Command python).Source

if (-not (Test-Path $ScriptPath)) {
    throw "Could not find $ScriptPath — run this from the repo's scripts\ directory."
}

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Weekly WoW guild board cast-art refresh (Blizzard transmog diff + regenerate changed characters)." `
    -Force

Write-Host "Registered scheduled task '$TaskName': every $DayOfWeek at $At."
Write-Host "Logs land in $RepoRoot\logs\weekly_cast_refresh.log on every run."
Write-Host "To remove it later: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
