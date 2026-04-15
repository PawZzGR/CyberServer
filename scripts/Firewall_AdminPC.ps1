# Firewall Rule for ADMIN PC
# Allows external connections on port 5001 so UserClients can download files
# Run as Administrator

Write-Host "Creating firewall rule for CyberAdmin..." -ForegroundColor Cyan

New-NetFirewallRule -DisplayName "CyberAdmin - Allow Port 5001 Inbound" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 5001 `
    -Action Allow `
    -Profile Any

Write-Host "Done! Port 5001 is now open for file sharing." -ForegroundColor Green
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
