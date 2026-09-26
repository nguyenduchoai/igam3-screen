# Bộ cài igam3-screen cho Windows 10/11 (THỬ NGHIỆM): màn hình 3.5" Turing Smart Screen / TURZX (USB 1a86:5722).
# Nháy đúp install-windows.cmd, hoặc:
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1 [-Title "Tên máy"] [-Tag "DePIN NODE"] [-Dir C:\...]
# Chạy lại bộ cài trên máy đã cài là nâng cấp: cấu hình, ảnh và mật khẩu web được giữ nguyên.
param(
    [string]$Dir = (Join-Path $env:USERPROFILE "igam3-screen"),
    [string]$Title,
    [string]$Tag
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Src = $PSScriptRoot

function Say([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[!] $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "[x] $Message" -ForegroundColor Red; exit 1 }

Say "igam3-screen $(Get-Content (Join-Path $Src 'VERSION')) cho Windows (thử nghiệm) -> $Dir"

# 1. Python 3.11+: python.org / winget build (the Microsoft Store "python" alias does not count)
function Get-Python {
    $versionCheck = "import sys; print('%d.%d' % sys.version_info[:2])"
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $version = & $launcher.Source -3 -c $versionCheck 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) { return @{ Exe = $launcher.Source; Args = @("-3"); Version = "$version" } }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike "*WindowsApps*") {
        $version = & $python.Source -c $versionCheck 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) { return @{ Exe = $python.Source; Args = @(); Version = "$version" } }
    }
    return $null
}

$Python = Get-Python
if (-not $Python -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    $answer = Read-Host "Máy chưa có Python. Cài Python 3.13 bằng winget? [C/k]"
    if ($answer -eq "" -or $answer -match "^[cCyY]") {
        winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $Python = Get-Python
    }
}
if (-not $Python) {
    Fail "Cần Python 3.11 trở lên: tải ở https://www.python.org/downloads/ (tick 'Add python.exe to PATH') rồi chạy lại bộ cài."
}
if ([version]$Python.Version -lt [version]"3.11") { Fail "Python $($Python.Version) quá cũ, cần 3.11 trở lên." }
Say "Dùng Python $($Python.Version)"

$Cli = Join-Path $Dir "tools\igam3_screen.py"
$VenvPython = Join-Path $Dir ".venv\Scripts\python.exe"

# 2. Upgrade: stop what runs from this folder, keep what was set on this machine
$Keep = @("app\config.yaml", "app\res\themes\iGam3\custom.yaml", "settings.yaml", "web.yaml", "images", "uploads")
$Backup = Join-Path $env:TEMP ("igam3-screen-keep-" + [guid]::NewGuid())
if (Test-Path $Cli) {
    Say "Đã có bản cài: nâng cấp, giữ nguyên cấu hình, ảnh và mật khẩu"
    if (Test-Path $VenvPython) { & $VenvPython $Cli stop | Out-Null }
    Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Dir) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $photos = Get-ChildItem (Join-Path $Dir "app\res\themes\iGam3") -Filter "photo.*" -Name -ErrorAction SilentlyContinue |
        ForEach-Object { "app\res\themes\iGam3\$_" }
    foreach ($item in @($Keep) + @($photos)) {
        $from = Join-Path $Dir $item
        if (Test-Path $from) {
            $to = Join-Path $Backup $item
            New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
            Copy-Item $from $to -Recurse -Force
        }
    }
}

# 3. Program files
Say "Chép chương trình"
New-Item -ItemType Directory -Force $Dir | Out-Null
if ((Resolve-Path $Src).Path.TrimEnd("\") -ne (Resolve-Path $Dir).Path.TrimEnd("\")) {
    Copy-Item (Join-Path $Src "*") $Dir -Recurse -Force
}
if (Test-Path $Backup) {
    Copy-Item (Join-Path $Backup "*") $Dir -Recurse -Force
    Remove-Item $Backup -Recurse -Force
}

# 4. Python environment and libraries (downloaded from the Internet)
Say "Chuẩn bị môi trường Python và tải thư viện (cần Internet)"
if (-not (Test-Path $VenvPython)) {
    & $Python.Exe @($Python.Args + @("-m", "venv", (Join-Path $Dir ".venv")))
    if ($LASTEXITCODE -ne 0) { Fail "Không tạo được môi trường Python." }
}
& $VenvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $Dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Không cài được thư viện Python. Kiểm tra mạng rồi chạy lại bộ cài." }

# 5. Machine settings, Start menu shortcuts, Ctrl+Alt+Q, start at logon
Say "Cấu hình cho máy này"
$InitArgs = @("init")
if ($Title) { $InitArgs += @("--title", $Title) }
if ($Tag) { $InitArgs += @("--tag", $Tag) }
& $VenvPython $Cli @InitArgs
if ($LASTEXITCODE -ne 0) { Fail "Không cấu hình được. Xem thông báo ở trên." }
Say "Tạo lối tắt trong menu Start, phím tắt Ctrl+Alt+Q, tự chạy khi đăng nhập"
& $VenvPython $Cli install --enable
& $VenvPython $Cli shortcut on

# 6. "igam3-screen" command in new terminal windows
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if (-not (($userPath -split ";") -contains $Dir)) {
    [Environment]::SetEnvironmentVariable("Path", (($userPath.TrimEnd(";") + ";" + $Dir).TrimStart(";")), "User")
}

Write-Host ""
Say "Xong! igam3-screen đã cài ở $Dir"
Write-Host "  - Màn hình nhỏ hiện bảng thông số sau khoảng 10 giây."
Write-Host "    Nếu app TURZX đang chạy, nó chiếm màn hình: tắt app đó (và bỏ khỏi Startup) rồi chạy: igam3-screen start"
Write-Host "  - Giao diện quản lý: menu Start > iGam3 Screen"
Write-Host "  - Phím tắt Ctrl+Alt+Q: hiện mã QR trên màn nhỏ"
Write-Host "  - Mở cửa sổ lệnh mới để dùng lệnh: igam3-screen status, igam3-screen --help"
Write-Host "  - Hướng dẫn đầy đủ: $(Join-Path $Dir 'README.md')"
Write-Host ""
Start-Sleep -Seconds 8
& $VenvPython $Cli status
