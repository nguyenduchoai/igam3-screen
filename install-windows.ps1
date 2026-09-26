# igam3-screen installer for Windows 10/11 (EXPERIMENTAL): 3.5" Turing Smart Screen / TURZX (USB 1a86:5722).
# Double-click install-windows.cmd, or:
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1 [-Title "Name"] [-Tag "DePIN NODE"] [-Lang vi|en] [-Dir C:\...]
# Running it again on an installed computer upgrades it: the settings, pictures and web password are kept.
# Messages are in Vietnamese on Vietnamese Windows, in English otherwise (or: -Lang vi|en).
param(
    [string]$Dir = (Join-Path $env:USERPROFILE "igam3-screen"),
    [string]$Title,
    [string]$Tag,
    [ValidateSet("vi", "en")][string]$Lang
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Src = $PSScriptRoot

$Vietnamese = if ($Lang) { $Lang -eq "vi" } else { (Get-UICulture).Name -like "vi*" }
function T([string]$Vn, [string]$En) { if ($Vietnamese) { $Vn } else { $En } }  # T "Tiếng Việt" "English"
function Say([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[!] $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "[x] $Message" -ForegroundColor Red; exit 1 }

Say "igam3-screen $(Get-Content (Join-Path $Src 'VERSION')) $(T 'cho Windows (thử nghiệm)' 'for Windows (experimental)') -> $Dir"

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
    $answer = Read-Host (T "Máy chưa có Python. Cài Python 3.13 bằng winget? [C/k]" "Python is missing. Install Python 3.13 with winget? [Y/n]")
    if ($answer -eq "" -or $answer -match "^[cCyY]") {
        winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $Python = Get-Python
    }
}
if (-not $Python) {
    Fail (T "Cần Python 3.11 trở lên: tải ở https://www.python.org/downloads/ (tick 'Add python.exe to PATH') rồi chạy lại bộ cài." `
            "Python 3.11 or newer is required: get it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run the installer again.")
}
if ([version]$Python.Version -lt [version]"3.11") { Fail (T "Python $($Python.Version) quá cũ, cần 3.11 trở lên." "Python $($Python.Version) is too old, 3.11 or newer is required.") }
Say "$(T 'Dùng Python' 'Using Python') $($Python.Version)"

$Cli = Join-Path $Dir "tools\igam3_screen.py"
$VenvPython = Join-Path $Dir ".venv\Scripts\python.exe"

# 2. Upgrade: stop what runs from this folder, keep what was set on this machine
$Keep = @("app\config.yaml", "app\res\themes\iGam3\custom.yaml", "settings.yaml", "web.yaml", "images", "uploads")
$Backup = Join-Path $env:TEMP ("igam3-screen-keep-" + [guid]::NewGuid())
if (Test-Path $Cli) {
    Say (T "Đã có bản cài: nâng cấp, giữ nguyên cấu hình, ảnh và mật khẩu" "Already installed: upgrading, keeping the settings, pictures and password")
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
Say (T "Chép chương trình" "Copying the program")
New-Item -ItemType Directory -Force $Dir | Out-Null
if ((Resolve-Path $Src).Path.TrimEnd("\") -ne (Resolve-Path $Dir).Path.TrimEnd("\")) {
    Copy-Item (Join-Path $Src "*") $Dir -Recurse -Force
}
if (Test-Path $Backup) {
    Copy-Item (Join-Path $Backup "*") $Dir -Recurse -Force
    Remove-Item $Backup -Recurse -Force
}

# 4. Python environment and libraries (downloaded from the Internet)
Say (T "Chuẩn bị môi trường Python và tải thư viện (cần Internet)" "Preparing Python and downloading the libraries (needs the Internet)")
if (-not (Test-Path $VenvPython)) {
    & $Python.Exe @($Python.Args + @("-m", "venv", (Join-Path $Dir ".venv")))
    if ($LASTEXITCODE -ne 0) { Fail (T "Không tạo được môi trường Python." "Cannot create the Python environment.") }
}
& $VenvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $Dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail (T "Không cài được thư viện Python. Kiểm tra mạng rồi chạy lại bộ cài." "Cannot install the Python libraries. Check the network and run the installer again.") }

# 5. Machine settings, Start menu shortcuts, Ctrl+Alt+Q, start at logon
Say (T "Cấu hình cho máy này" "Settings for this computer")
$InitArgs = @("init")
if ($Title) { $InitArgs += @("--title", $Title) }
if ($Tag) { $InitArgs += @("--tag", $Tag) }
if ($Lang) { $InitArgs += @("--language", $Lang) }
& $VenvPython $Cli @InitArgs
if ($LASTEXITCODE -ne 0) { Fail (T "Không cấu hình được. Xem thông báo ở trên." "Setup failed, see the messages above.") }
Say (T "Tạo lối tắt trong menu Start, phím tắt Ctrl+Alt+Q, tự chạy khi đăng nhập" "Start menu shortcuts, Ctrl+Alt+Q shortcut, start at logon")
& $VenvPython $Cli install --enable
& $VenvPython $Cli shortcut on

# 6. "igam3-screen" command in new terminal windows
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if (-not (($userPath -split ";") -contains $Dir)) {
    [Environment]::SetEnvironmentVariable("Path", (($userPath.TrimEnd(";") + ";" + $Dir).TrimStart(";")), "User")
}

Write-Host ""
if ($Vietnamese) {
    Say "Xong! igam3-screen đã cài ở $Dir"
    Write-Host "  - Màn hình nhỏ hiện bảng thông số sau khoảng 10 giây."
    Write-Host "    Nếu app TURZX đang chạy, nó chiếm màn hình: tắt app đó (và bỏ khỏi Startup) rồi chạy: igam3-screen start"
    Write-Host "  - Giao diện quản lý: menu Start > iGam3 Screen"
    Write-Host "  - Phím tắt Ctrl+Alt+Q: hiện mã QR trên màn nhỏ"
    Write-Host "  - Mở cửa sổ lệnh mới để dùng lệnh: igam3-screen status, igam3-screen --help"
    Write-Host "  - Đổi ngôn ngữ: igam3-screen language en   (hoặc vi, auto)"
    Write-Host "  - Hướng dẫn đầy đủ: $(Join-Path $Dir 'README.vi.md')"
} else {
    Say "Done! igam3-screen is installed in $Dir"
    Write-Host "  - The small screen shows the dashboard in about 10 seconds."
    Write-Host "    If the TURZX app is running, it holds the screen: close it (and remove it from Startup), then run: igam3-screen start"
    Write-Host "  - Web panel: Start menu > iGam3 Screen"
    Write-Host "  - Shortcut Ctrl+Alt+Q: QR code on the small screen"
    Write-Host "  - Open a new terminal window for the command: igam3-screen status, igam3-screen --help"
    Write-Host "  - Language: igam3-screen language vi   (or en, auto)"
    Write-Host "  - Full guide: $(Join-Path $Dir 'README.md')"
}
Write-Host ""
Start-Sleep -Seconds 8
& $VenvPython $Cli status
