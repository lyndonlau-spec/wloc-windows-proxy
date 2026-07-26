#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\WlocProxy'
$taskName = 'WLOC Proxy'
$firewallName = 'WLOC Proxy'
$watchTaskName = 'WLOC Network Watch'
$hotspotFirewallName = 'WLOC Proxy Mobile Hotspot'
$shortcut = Join-Path $env:PUBLIC 'Desktop\WLOC Location Settings.url'

Stop-ScheduledTask -TaskName $watchTaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $watchTaskName -Confirm:$false -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName $hotspotFirewallName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName 'WLOC Proxy Mobile Hotspot 8080' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Remove-Item -Force $shortcut -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue

Write-Host 'WLOC Proxy has been removed.' -ForegroundColor Green
Write-Host 'Remove the mitmproxy CA profile from each iPhone separately.'
