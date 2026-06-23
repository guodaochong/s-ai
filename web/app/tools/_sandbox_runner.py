from __future__ import annotations

import json
import sys
import math

import numpy as np
from scipy.spatial import Voronoi

code = sys.stdin.read()
args_str = sys.argv[1] if len(sys.argv) > 1 else "{}"
tool_name = sys.argv[2] if len(sys.argv) > 2 else ""

args = json.loads(args_str)

namespace: dict = {
    "math": math,
    "json": json,
    "np": np,
    "numpy": np,
    "Voronoi": Voronoi,
    "base64": __import__("base64"),
}

try:
    exec(code, namespace)
except Exception as e:
    print(json.dumps({"error": f"Code definition error: {str(e)[:300]}"}, ensure_ascii=False))
    sys.exit(0)

fn = namespace.get(tool_name) if tool_name else None
if not fn:
    for k, v in namespace.items():
        if k.startswith("compute_") and callable(v):
            fn = v
            break

if not fn:
    print(json.dumps({"error": f"Function {tool_name} not found"}, ensure_ascii=False))
    sys.exit(0)

try:
    if args:
        try:
            result = fn(**args)
        except TypeError:
            result = fn(args)
    else:
        result = fn()
except Exception as e:
    print(json.dumps({"error": str(e)[:500]}, ensure_ascii=False))
    sys.exit(0)

if isinstance(result, dict):
    print(json.dumps({"result": result}, default=str, ensure_ascii=False))
else:
    print(json.dumps({"result": {"result": str(result)}}, default=str, ensure_ascii=False))
