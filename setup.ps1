# 쇼핑쇼츠메이커 설치 스크립트 (Windows, PowerShell 7 / 5.1)
# 사용: 폴더에서  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
$HOME_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $HOME_DIR
Remove-Item env:PIP_PREFIX, env:PYTHONHOME, env:VIRTUAL_ENV -ErrorAction SilentlyContinue

Write-Host "== 1/5 Python 확인"
$py = $null
foreach ($c in @("py -3.13", "py -3.12", "py -3.11", "python")) {
    try { $v = & cmd /c "$c --version" 2>$null; if ($LASTEXITCODE -eq 0 -and $v -match "Python 3\.(1[0-3])") { $py = $c; break } } catch {}
}
if (-not $py) { Write-Host "Python 3.10~3.13 이 필요합니다: winget install Python.Python.3.13" -ForegroundColor Red; exit 1 }
Write-Host "   $py"

Write-Host "== 2/5 ffmpeg 확인"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "   ffmpeg 설치 시도 (winget)..."
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements | Out-Null
    Write-Host "   설치 후 새 터미널을 열고 setup.ps1 을 다시 실행하세요." -ForegroundColor Yellow
    exit 1
}

Write-Host "== 3/5 가상환경 + 패키지 설치 (몇 분 걸릴 수 있음)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { cmd /c "$py -m venv .venv" }
& .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt

Write-Host "== 4/5 효과음 생성 + 폴더 준비"
New-Item -ItemType Directory -Force assets\sfx, assets\bgm, assets\fonts, projects | Out-Null
if (-not (Test-Path assets\sfx\whoosh.wav)) {
    ffmpeg -y -loglevel error -f lavfi -i "anoisesrc=d=0.45:c=pink:a=0.8" -af "bandpass=f=1800:w=1500,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.25,volume=2" -ar 44100 assets\sfx\whoosh.wav
    ffmpeg -y -loglevel error -f lavfi -i "sine=f=880:d=0.15" -af "afade=t=out:st=0.02:d=0.13,volume=0.9" -ar 44100 assets\sfx\pop.wav
    ffmpeg -y -loglevel error -f lavfi -i "sine=f=1320:d=0.12" -f lavfi -i "sine=f=1760:d=0.25" -filter_complex "[0]afade=t=out:st=0.05:d=0.07[a];[1]adelay=90|90,afade=t=out:st=0.1:d=0.25[b];[a][b]amix=inputs=2:normalize=0,volume=0.7" -ar 44100 assets\sfx\ding.wav
}

Write-Host "== 폰트 확인 (Pretendard, OFL 라이선스)"
$fontDirs = @("$env:WINDIR\Fonts", "$env:LOCALAPPDATA\Microsoft\Windows\Fonts", (Join-Path $HOME_DIR "assets\fonts"))
$need = @("Pretendard-Bold.otf", "Pretendard-ExtraBold.otf", "Pretendard-Black.otf") | Where-Object { $f = $_; -not ($fontDirs | Where-Object { Test-Path (Join-Path $_ $f) }) }
if ($need) {
    try {
        $z = Join-Path $env:TEMP "pretendard.zip"
        Invoke-WebRequest "https://github.com/orioncactus/pretendard/releases/download/v1.3.9/Pretendard-1.3.9.zip" -OutFile $z
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($z)
        foreach ($n in $need) {
            $e = $zip.Entries | Where-Object { $_.FullName -eq "public/static/$n" }
            if ($e) { [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $HOME_DIR "assets\fonts\$n"), $true) }
        }
        $zip.Dispose()
        Write-Host "   Pretendard 내려받음 -> assets\fonts"
    } catch { Write-Host "   폰트 다운로드 실패 -> 맑은 고딕 Bold 로 대체됩니다" -ForegroundColor Yellow }
} else { Write-Host "   OK" }

Write-Host "== 5/5 Claude Code / Codex 스킬 등록"
$skillSrc = Join-Path $HOME_DIR "skill"
$targets = @("$env:USERPROFILE\.claude\skills\shopping-shorts-maker", "$env:USERPROFILE\.codex\skills\shopping-shorts-maker")
foreach ($t in $targets) {
    New-Item -ItemType Directory -Force $t, "$t\references" | Out-Null
    $txt = (Get-Content "$skillSrc\SKILL.md" -Raw -Encoding utf8).Replace("__SSM_HOME__", $HOME_DIR)
    [System.IO.File]::WriteAllText("$t\SKILL.md", $txt, (New-Object System.Text.UTF8Encoding $false))  # BOM 없이
    Copy-Item "$skillSrc\references\*" "$t\references\" -Force
    Write-Host "   $t"
}
# Aside 사용자면 Aside 스킬도 등록 (샤오홍슈 직접 검색/다운로드 버전)
$asideRoot = Join-Path $env:USERPROFILE ".aside\u"
if (Test-Path $asideRoot) {
    foreach ($acc in Get-ChildItem $asideRoot -Directory) {
        $t = Join-Path $acc.FullName "skills\user\shopping-shorts-maker"
        New-Item -ItemType Directory -Force "$t\scripts" | Out-Null
        $fwd = $HOME_DIR.Replace("\", "/")
        $txt = (Get-Content "$HOME_DIR\aside-skill\SKILL.md" -Raw -Encoding utf8).Replace("__SSM_HOME_FWD__", $fwd).Replace("__SSM_HOME__", $HOME_DIR).Replace("__ASIDE_SKILL_DIR__", $t.Replace("\", "/"))
        [System.IO.File]::WriteAllText("$t\SKILL.md", $txt, (New-Object System.Text.UTF8Encoding $false))
        Copy-Item "$HOME_DIR\aside-skill\scripts\xhs.js" "$t\scripts\" -Force
        Write-Host "   $t (Aside)"
    }
}
& .\ssm.cmd doctor
Write-Host ""
Write-Host "설치 완료! Claude Code 나 Codex 에서 '이 링크로 쇼핑쇼츠 만들어줘 <링크>' 라고 말하면 됩니다." -ForegroundColor Green
