import httpx, json, sys, os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

url = "http://127.0.0.1:3000/api/chat/stream?q=%E6%9F%A5%E8%AF%A2HDPE%E7%AE%A1%E7%9A%84%E6%9B%BC%E5%AE%81%E7%B3%99%E7%8E%87"

with httpx.stream("GET", url, timeout=30) as resp:
    for line in resp.iter_lines():
        if not line.startswith("data: "):
            continue
        data = json.loads(line[6:])
        t = data.get("type", "")

        if t == "thinking_start":
            print(f'  >>> THINK START: {data.get("agent")} ({data.get("label")})')
        elif t == "thinking":
            print(f'  [THINK:{data.get("agent")}] {data.get("content")}')
        elif t == "thinking_end":
            print(f'  <<< THINK END: {data.get("agent")}')
        elif t == "divider":
            print(f'  --- {data.get("content")} ---')
        elif t == "tool_start":
            print(f'  [CALL] {data.get("server")}.{data.get("tool")} ({data.get("step")}/{data.get("total")})')
        elif t == "tool_result":
            ms = data.get("elapsed_ms", 0)
            print(f'  [TOOL] {data.get("server")}.{data.get("tool")} OK ({ms}ms)')
            result = data.get("result", {})
            entries = result.get("results", [])
            for e in entries[:3]:
                name = e.get("surface", e.get("city", ""))
                if "n_typical" in e:
                    print(f'    {name}: n={e["n_typical"]}')
                elif "A1" in e:
                    print(f'    {name}: A1={e["A1"]}')
        elif t == "text":
            sys.stdout.write(data.get("content", ""))
            sys.stdout.flush()
        elif t == "done":
            print(f'\n  [DONE] {data.get("duration_ms")}ms, {data.get("tools_called")} tools')
        elif t == "tool_error":
            print(f'  [ERROR] {data.get("server")}.{data.get("tool")}: {data.get("error")}')
