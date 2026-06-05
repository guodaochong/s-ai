import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "servers" / "mcp-hydro"))
from sai_mcp_hydro.server import main

if __name__ == "__main__":
    main()
