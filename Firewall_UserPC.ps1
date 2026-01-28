# Firewall Rule for USER PC
# Allows outgoing connections on port 5001 to download files from AdminClient
# Run as Administrator

Write-Host "Creating firewall rule for CyberUser..." -ForegroundColor Cyan

New-NetFirewallRule -DisplayName "CyberUser - Allow Port 5001 Outbound" `
    -Direction Outbound `
    -Protocol TCP `
    -RemotePort 5001 `
    -Action Allow `
    -Profile Any

Write-Host "Done! Port 5001 is now open for outgoing connections." -ForegroundColor Green
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
