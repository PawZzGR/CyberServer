# Firewall Rule for SERVER PC
# Allows incoming connections on port 5000 for the main API
# Run as Administrator

Write-Host "Creating firewall rule for CyberServer..." -ForegroundColor Cyan

New-NetFirewallRule -DisplayName "CyberServer - Allow Port 5000 Inbound" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 5000 `
    -Action Allow `
    -Profile Any

Write-Host "Done! Port 5000 is now open for API connections." -ForegroundColor Green
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
