# FIVEL Control - aplicar atualizacao (rodar no PowerShell como Administrador)
#   1) confere se o Python do servico tem as bibliotecas necessarias (se faltar, para sem mexer em nada)
#   2) para o FIVEL_API e faz backup do codigo, do banco e da tela em C:\FIVEL_Control\backup_<data>
#   3) copia os arquivos novos de C:\FIVEL_Control\atualizacao e liga o FIVEL_API
#   4) testa se a API voltou; se nao voltar em 60 s, restaura a versao anterior sozinho
$ErrorActionPreference = 'Stop'
$base = 'C:\FIVEL_Control'
$origem = Join-Path $base 'atualizacao'
$backup = Join-Path $base ('backup_' + (Get-Date -Format 'yyyy-MM-dd_HHmm'))
$modulos = "'flask','flask_cors','fdb','requests','dotenv','werkzeug','waitress'"

function Get-PythonDoServico {
    $chave = 'HKLM:\SYSTEM\CurrentControlSet\Services\FIVEL_API\Parameters'
    $app = (Get-ItemProperty -Path $chave -Name Application -ErrorAction SilentlyContinue).Application
    if ($app -and (Test-Path $app)) { return $app }
    return 'C:\Users\Computador\AppData\Local\Python\pythoncore-3.14-64\python.exe'
}

function Test-ApiNoAr {
    # Sem login, /api/auth/eu responde 401: isso basta para saber que a API subiu.
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

function Restaurar-Codigo($pasta) {
    Get-ChildItem $pasta -Filter *.py | Copy-Item -Destination $base -Force
    if (Test-Path "$pasta\dist") { Copy-Item "$pasta\dist\*" -Destination "$base\dist" -Recurse -Force }
}

# 1) Bibliotecas
$python = Get-PythonDoServico
$faltando = & $python -c "import importlib.util as u; print(' '.join(m for m in ($modulos) if u.find_spec(m) is None))"
if ($faltando) {
    Write-Host "Faltam bibliotecas no Python do servico: $faltando" -ForegroundColor Red
    Write-Host "Instale com:  & '$python' -m pip install $faltando"
    Write-Host 'Nada foi alterado.'
    exit 1
}

# 2) e 3) Backup e copia
Write-Host 'Parando o servico FIVEL_API...'
Stop-Service FIVEL_API
try {
    New-Item -ItemType Directory -Path $backup | Out-Null
    Get-ChildItem $base -Filter *.py | Copy-Item -Destination $backup
    Get-ChildItem "$base\kanban_status.db*" | Copy-Item -Destination $backup
    if (Test-Path "$base\dist") { Copy-Item "$base\dist" -Destination "$backup\dist" -Recurse }
    Write-Host "Backup salvo em $backup"

    Get-ChildItem $origem -Filter *.py | Copy-Item -Destination $base -Force
    if (Test-Path "$origem\dist") { Copy-Item "$origem\dist\*" -Destination "$base\dist" -Recurse -Force }
    Write-Host 'Arquivos novos copiados.'
}
finally {
    Write-Host 'Iniciando o servico FIVEL_API...'
    Start-Service FIVEL_API
}

# 4) Verificacao
if (Test-ApiNoAr) {
    Get-Service FIVEL_API, FIVEL_Web | Format-Table Name, Status
    if (Test-Path "$base\logs\fivel.log") { Get-Content "$base\logs\fivel.log" -Tail 2 }
    Write-Host 'Pronto. A API respondeu. Recarregue o FIVEL com Ctrl+F5.' -ForegroundColor Green
    exit 0
}

Write-Host 'A API nao respondeu em 60 s. Voltando a versao anterior...' -ForegroundColor Red
Stop-Service FIVEL_API -ErrorAction SilentlyContinue
Restaurar-Codigo $backup
Start-Service FIVEL_API
if (Test-ApiNoAr) {
    Write-Host 'Versao anterior restaurada e funcionando. O motivo da falha esta em C:\FIVEL_Control\logs\fivel.log' -ForegroundColor Yellow
} else {
    Write-Host "ATENCAO: a API nao voltou nem na versao anterior. Backup em $backup" -ForegroundColor Red
}
exit 1
