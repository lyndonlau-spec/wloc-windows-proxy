#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$ListenHost = '0.0.0.0',
    [ValidateRange(1, 65535)][int]$ProxyPort = 8080,
    [ValidateRange(1, 65535)][int]$SettingsPort = 8081,
    [string]$UpstreamProxy = ''
)

$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\WlocProxy'
$taskName = 'WLOC Proxy'
$firewallName = 'WLOC Proxy'
$shortcut = Join-Path $env:PUBLIC 'Desktop\WLOC Location Settings.url'

if ($ProxyPort -eq $SettingsPort) {
    throw 'ProxyPort and SettingsPort must be different.'
}
$parsedAddress = $null
if ($ListenHost -ne '0.0.0.0' -and -not [Net.IPAddress]::TryParse($ListenHost, [ref]$parsedAddress)) {
    throw 'ListenHost must be 0.0.0.0 or an IPv4 address assigned to this computer.'
}
if ($parsedAddress -and $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'Only IPv4 ListenHost values are supported.'
}
if ($UpstreamProxy) {
    $upstreamUri = [Uri]$UpstreamProxy
    if ($upstreamUri.Scheme -notin @('http', 'https')) {
        throw 'UpstreamProxy must use http:// or https://.'
    }
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python 3.12 or newer is required. Install it from https://www.python.org/downloads/windows/ and run this script again.'
}
$python = $pythonCommand.Source
$pythonVersion = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$versionParts = $pythonVersion.Split('.')
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 12)) {
    throw "Python 3.12 or newer is required; found $pythonVersion."
}

foreach ($requiredFile in @('wloc_proxy.py', 'run.ps1', 'requirements.txt', 'uninstall.ps1')) {
    if (-not (Test-Path (Join-Path $PSScriptRoot $requiredFile))) {
        throw "Missing $requiredFile next to install.ps1."
    }
}

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
New-Item -ItemType Directory -Force $root | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot 'wloc_proxy.py') $root
Copy-Item -Force (Join-Path $PSScriptRoot 'run.ps1') $root
Copy-Item -Force (Join-Path $PSScriptRoot 'requirements.txt') $root
Copy-Item -Force (Join-Path $PSScriptRoot 'uninstall.ps1') $root

$venvPython = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    & $python -m venv (Join-Path $root 'venv')
}
& $venvPython -m pip install --disable-pip-version-check --upgrade -r (Join-Path $root 'requirements.txt')

$config = [ordered]@{
    listenHost = $ListenHost
    proxyPort = $ProxyPort
    settingsPort = $SettingsPort
    upstreamProxy = $UpstreamProxy
}
$config | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $root 'config.json')

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\ProgramData\WlocProxy\run.ps1"'
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-ScheduledTask `
    -TaskName $taskName `
    -Description 'Apple WLOC response rewriting proxy for authorized iOS testing' `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $taskSettings `
    -Force | Out-Null

Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
$firewallArgs = @{
    DisplayName = $firewallName
    Description = 'Allow WLOC proxy only from the private local subnet'
    Direction = 'Inbound'
    Action = 'Allow'
    Protocol = 'TCP'
    LocalPort = $ProxyPort
    RemoteAddress = 'LocalSubnet'
    Profile = 'Private'
}
if ($ListenHost -ne '0.0.0.0') {
    $firewallArgs.LocalAddress = $ListenHost
}
New-NetFirewallRule @firewallArgs | Out-Null

Set-Content -Encoding ASCII $shortcut "[InternetShortcut]`r`nURL=http://127.0.0.1:$SettingsPort/`r`n"
Start-ScheduledTask -TaskName $taskName

$healthy = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$SettingsPort/health" -TimeoutSec 2
        if ($health.ok) {
            $healthy = $true
            break
        }
    }
    catch {}
}
if (-not $healthy) {
    throw "The task was installed but did not become healthy. Check $root\wloc-proxy.log."
}

$displayIp = $ListenHost
if ($ListenHost -eq '0.0.0.0') {
    $displayIp = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Select-Object -First 1
}

Write-Host ''
Write-Host 'WLOC Proxy installed successfully.' -ForegroundColor Green
Write-Host "Settings page: http://127.0.0.1:$SettingsPort/"
Write-Host "iPhone Wi-Fi proxy: $displayIp`:$ProxyPort"
Write-Host 'After configuring the proxy on iPhone, open http://mitm.it to install the CA certificate.'
