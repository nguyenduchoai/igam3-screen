# Uninstall igam3-screen on Windows: stops the screen, removes the shortcuts, hotkey, start at logon and command path.
# Run it from Start menu > iGam3 Screen > iGam3 Screen - Uninstall, or:
#   powershell -ExecutionPolicy Bypass -File uninstall-windows.ps1
$Vietnamese = (Get-UICulture).Name -like "vi*"
function T([string]$Vn, [string]$En) { if ($Vietnamese) { $Vn } else { $En } }  # T "Tiếng Việt" "English"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Dir = $PSScriptRoot
$VenvPython = Join-Path $Dir ".venv\Scripts\python.exe"
$Cli = Join-Path $Dir "tools\igam3_screen.py"

if (Test-Path $VenvPython) {
    & $VenvPython $Cli shortcut off
    & $VenvPython $Cli web --lan off | Out-Null
    & $VenvPython $Cli disable
}
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Dir) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
Remove-Item (Join-Path $programs "iGam3 Screen") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $programs "Startup\iGam3 Screen*.lnk") -Force -ErrorAction SilentlyContinue

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $kept = ($userPath -split ";") | Where-Object { $_ -and $_ -ne $Dir }
    [Environment]::SetEnvironmentVariable("Path", ($kept -join ";"), "User")
}
Write-Host (T "Đã gỡ lối tắt, phím tắt, tự chạy và lệnh igam3-screen." "Removed the shortcuts, hotkey, start at logon and the igam3-screen command.")

$answer = Read-Host (T "Xoá luôn thư mục $Dir (cả cấu hình, ảnh, mật khẩu)? [c/K]" "Also delete the folder $Dir (settings, pictures, password)? [y/N]")
if ($answer -match "^[cCyY]") {
    Set-Location $env:TEMP
    Remove-Item $Dir -Recurse -Force
    Write-Host "$(T 'Đã xoá' 'Deleted') $Dir."
} else {
    Write-Host (T "Giữ lại $Dir. Cài lại bất cứ lúc nào bằng install-windows.cmd." "Kept $Dir. Reinstall any time with install-windows.cmd.")
}
