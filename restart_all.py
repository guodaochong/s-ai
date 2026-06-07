import subprocess, time, socket, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
subprocess.Popen([r'D:\App\anaconda3\python.exe', r'D:\jumpingbirds\S-AI\start_all.py'], cwd=r'D:\jumpingbirds\S-AI', creationflags=0x08000000)
time.sleep(18)
for p in [5001,5002,5003,5004,5005,5006,5007,3000]:
    s = socket.socket(); s.settimeout(1)
    r = s.connect_ex(('127.0.0.1', p)); s.close()
    status = 'UP' if r == 0 else 'DOWN'
    print(f'Port {p}: {status}')
