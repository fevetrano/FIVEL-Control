# FIVEL Control - volta a versao anterior (rodar no PowerShell como Administrador)
# Usa o backup mais recente (backup_<data>). O banco NAO e restaurado, para nao perder
# os status marcados desde a atualizacao. Para restaurar o banco, veja backups_banco.
$ErrorActionPreference = 'Stop'
$base = 'C:\FIVEL_Control'
$backup = Get-ChildItem $base -Directory -Filter 'backup_*' | Sort-Object Name -Descending | Select-Object -First 1
if (-not $backup) { throw 'Nenhum backup encontrado.' }

function Test-ApiNoAr {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/auth/eu' -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            $resp = $_.Exception.Response
            if ($resp -and [int]$resp.StatusCode -eq 401) { return $true }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-Host "Voltando para a versao salva em $($backup.FullName)"
Stop-Service FIVEL_API
try {
    Get-ChildItem $backup.FullName -Filter *.py | Copy-Item -Destination $base -Force
    if (Test-Path "$($backup.FullName)\dist") { Copy-Item "$($backup.FullName)\dist\*" -Destination "$base\dist" -Recurse -Force }
}
finally {
    Start-Service FIVEL_API
}
if (Test-ApiNoAr) {
    Write-Host 'Versao anterior restaurada. Recarregue o FIVEL com Ctrl+F5.' -ForegroundColor Green
} else {
    Write-Host 'A API nao respondeu. Veja C:\FIVEL_Control\logs\fivel.log' -ForegroundColor Red
}
Get-Service FIVEL_API, FIVEL_Web | Format-Table Name, Status
