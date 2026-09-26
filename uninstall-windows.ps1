# Gỡ igam3-screen trên Windows: dừng màn hình, xoá lối tắt, phím tắt, tự chạy và đường dẫn lệnh.
# Chạy từ menu Start > iGam3 Screen > Gỡ cài đặt iGam3 Screen, hoặc:
#   powershell -ExecutionPolicy Bypass -File uninstall-windows.ps1
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
Write-Host "Đã gỡ lối tắt, phím tắt, tự chạy và lệnh igam3-screen."

$answer = Read-Host "Xoá luôn thư mục $Dir (cả cấu hình, ảnh, mật khẩu)? [c/K]"
if ($answer -match "^[cC]") {
    Set-Location $env:TEMP
    Remove-Item $Dir -Recurse -Force
    Write-Host "Đã xoá $Dir."
} else {
    Write-Host "Giữ lại $Dir. Cài lại bất cứ lúc nào bằng install-windows.cmd."
}
