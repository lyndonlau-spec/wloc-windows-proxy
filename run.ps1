$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $root 'config.json'
$mitmdump = Join-Path $root 'venv\Scripts\mitmdump.exe'
$addon = Join-Path $root 'wloc_proxy.py'
$confdir = Join-Path $root 'mitmproxy'
$log = Join-Path $root 'wloc-proxy.log'

while ($true) {
    try {
        $config = Get-Content -Raw -Encoding UTF8 $configPath | ConvertFrom-Json
        $listenHost = [string]$config.listenHost
        $proxyPort = [int]$config.proxyPort
        $settingsPort = [int]$config.settingsPort
        $upstreamProxy = [string]$config.upstreamProxy

        if (-not $listenHost) { throw 'config.listenHost is required' }
        if ($proxyPort -lt 1 -or $proxyPort -gt 65535) { throw 'config.proxyPort must be between 1 and 65535' }
        if ($settingsPort -lt 1 -or $settingsPort -gt 65535) { throw 'config.settingsPort must be between 1 and 65535' }
        if ($proxyPort -eq $settingsPort) { throw 'proxyPort and settingsPort must be different' }

        if ($listenHost -notin @('0.0.0.0', '::')) {
            while (-not (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq $listenHost })) {
                Start-Sleep -Seconds 5
            }
        }

        if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) {
            Move-Item -Force $log "$log.previous"
        }

        $env:WLOC_HOME = $root
        $env:WLOC_SETTINGS_PORT = [string]$settingsPort
        $arguments = @(
            '--quiet',
            '--listen-host', $listenHost,
            '--listen-port', [string]$proxyPort,
            '--set', "confdir=$confdir",
            '--set', 'block_global=false',
            '--set', 'termlog_verbosity=info',
            '--scripts', $addon
        )
        if (-not [string]::IsNullOrWhiteSpace($upstreamProxy)) {
            $uri = [Uri]$upstreamProxy
            if ($uri.Scheme -notin @('http', 'https')) { throw 'upstreamProxy must use http:// or https://' }
            $arguments += @('--mode', "upstream:$upstreamProxy")
        }

        & $mitmdump @arguments 2>&1 | Out-File -FilePath $log -Encoding utf8 -Append
    }
    catch {
        $_ | Out-File -FilePath $log -Encoding utf8 -Append
    }

    Start-Sleep -Seconds 5
}
