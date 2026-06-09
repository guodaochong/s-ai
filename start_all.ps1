$py = "D:\App\anaconda3\python.exe"
$servers = @(
    @("D:\jumpingbirds\S-AI\servers\mcp-gis", "-m","sai_mcp_gis.server"),
    @("D:\jumpingbirds\S-AI\servers\mcp-data", "-m","sai_mcp_data.server"),
    @("D:\jumpingbirds\S-AI\servers\mcp-knowledge", "-m","sai_mcp_knowledge.server"),
    @("D:\jumpingbirds\S-AI\servers\mcp-map", "-m","sai_mcp_map.server"),
    @("D:\jumpingbirds\S-AI\servers\mcp-hydro", "-m","sai_mcp_hydro.server"),
    @("D:\jumpingbirds\S-AI\servers\mcp-flood", "-m","sai_mcp_flood.server"),
    @("D:\jumpingbirds\S-AI\servers\mcp-raster", "-m","sai_mcp_raster.server")
)
foreach ($s in $servers) {
    Push-Location -LiteralPath $s[0]
    Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList $s[1],$s[2]
    Write-Host "Started $($s[2])"
    Pop-Location
}
Push-Location -LiteralPath "D:\jumpingbirds\S-AI"
Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList "web\server.py"
Write-Host "Started web:3000"
Pop-Location
Start-Sleep -Seconds 12
netstat -ano | findstr "LISTENING" | findstr "500[1-7]\|3000"
