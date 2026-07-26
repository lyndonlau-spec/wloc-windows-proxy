$ErrorActionPreference = 'Continue'
$taskName = 'WLOC Proxy'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $root 'network-watch.log'

function Get-NetworkSignature {
    $parts = foreach ($route in Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue) {
        $address = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -First 1
        if (-not $address) { continue }

        $profile = Get-NetConnectionProfile -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue |
            Select-Object -First 1
        '{0}|{1}|{2}|{3}' -f $route.InterfaceIndex, $route.NextHop, $address.IPAddress, $profile.Name
    }
    return (@($parts | Sort-Object -Unique) -join ';')
}

function Write-WatchLog([string]$Message) {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) {
        Move-Item -Force $log "$log.previous"
    }
    "$(Get-Date -Format o) $Message" | Out-File -FilePath $log -Encoding utf8 -Append
}

$lastSignature = Get-NetworkSignature
Write-WatchLog "started signature=$lastSignature"

while ($true) {
    Start-Sleep -Seconds 3
    $signature = Get-NetworkSignature
    if (-not $signature -or $signature -eq $lastSignature) { continue }

    Start-Sleep -Seconds 7
    $settledSignature = Get-NetworkSignature
    if (-not $settledSignature -or $settledSignature -eq $lastSignature) { continue }

    try {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        Write-WatchLog "network changed old=$lastSignature new=$settledSignature; restarted $taskName"
        $lastSignature = $settledSignature
    }
    catch {
        Write-WatchLog "restart failed: $($_.Exception.Message)"
    }
}
