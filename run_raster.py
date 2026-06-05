import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "servers" / "mcp-raster"))
from sai_mcp_raster.server import main

if __name__ == "__main__":
    main()
