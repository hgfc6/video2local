$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到虚拟环境：$python。请先创建 .venv 并安装项目依赖。"
}

Push-Location $projectRoot
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot "build\pyinstaller-cache"
    & $python -m PyInstaller `
        --noconfirm `
        --noupx `
        --onefile `
        --windowed `
        --name "Video2Local" `
        --workpath "build\work" `
        --distpath "dist" `
        --specpath "build\spec" `
        --paths "src" `
        --collect-all "yt_dlp" `
        --collect-all "playwright" `
        "src\video2local\main.py"

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
    }

    Write-Host "打包完成：$projectRoot\dist\Video2Local.exe"
}
finally {
    Pop-Location
}
