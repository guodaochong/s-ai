import subprocess, sys, time, os

py = r"D:\App\anaconda3\python.exe"
base = r"D:\jumpingbirds\S-AI"

servers = [
    (f"{base}\\servers\\mcp-gis", ["-m", "sai_mcp_gis.server"]),
    (f"{base}\\servers\\mcp-data", ["-m", "sai_mcp_data.server"]),
    (f"{base}\\servers\\mcp-knowledge", ["-m", "sai_mcp_knowledge.server"]),
    (f"{base}\\servers\\mcp-map", ["-m", "sai_mcp_map.server"]),
    (f"{base}\\servers\\mcp-hydro", ["-m", "sai_mcp_hydro.server"]),
    (f"{base}\\servers\\mcp-flood", ["-m", "sai_mcp_flood.server"]),
    (f"{base}\\servers\\mcp-raster", ["-m", "sai_mcp_raster.server"]),
]

for cwd, args in servers:
    creationflags = 0x08000000  # CREATE_NO_WINDOW
    subprocess.Popen([py] + args, cwd=cwd, creationflags=creationflags)
    print(f"Started {args[1]} from {cwd}")

subprocess.Popen([py, "web\\server.py"], cwd=base, creationflags=creationflags)
print("Started web:3000")

print("Waiting 15s for services to start...")
time.sleep(15)

import socket
ports = [5011,5002,5003,5004,5015,5006,5007,3000]
for p in ports:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    result = s.connect_ex(("127.0.0.1", p))
    s.close()
    status = "UP" if result == 0 else "DOWN"
    print(f"  Port {p}: {status}")
