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

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
    "dict": dict, "divmod": divmod, "enumerate": enumerate, "filter": filter,
    "float": float, "format": format, "frozenset": frozenset, "hash": hash,
    "hex": hex, "id": id, "int": int, "isinstance": isinstance,
    "issubclass": issubclass, "iter": iter, "len": len, "list": list,
    "map": map, "max": max, "min": min, "next": next, "oct": oct,
    "ord": ord, "pow": pow, "print": print, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "set": set, "slice": slice,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "type": type,
    "zip": zip,
    "True": True, "False": False, "None": None,
    "ArithmeticError": ArithmeticError, "AssertionError": AssertionError,
    "AttributeError": AttributeError, "Exception": Exception,
    "FloatingPointError": FloatingPointError, "ImportError": ImportError,
    "IndexError": IndexError, "KeyError": KeyError, "LookupError": LookupError,
    "MemoryError": MemoryError, "NameError": NameError,
    "OverflowError": OverflowError, "RuntimeError": RuntimeError,
    "StopIteration": StopIteration, "SyntaxError": SyntaxError,
    "TypeError": TypeError, "ValueError": ValueError,
    "ZeroDivisionError": ZeroDivisionError,
}

_ALLOWED_IMPORT_ROOTS = frozenset({
    "math", "json", "numpy", "scipy", "base64",
    "statistics", "fractions", "decimal", "itertools", "functools",
    "collections", "re", "datetime",
})

_real_import = __import__

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORT_ROOTS:
        raise ImportError(f"Import of '{name}' is not allowed in sandbox")
    return _real_import(name, globals, locals, fromlist, level)

_SAFE_BUILTINS["__import__"] = _restricted_import

namespace: dict = {
    "__builtins__": _SAFE_BUILTINS,
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
