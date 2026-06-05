import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'servers/mcp-gis')

from sai_mcp_gis.server import app
import uvicorn

if __name__ == "__main__":
    print("Starting GIS server on port 5001...")
    uvicorn.run(app, host="127.0.0.1", port=5001, log_level="info")
