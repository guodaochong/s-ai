import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'servers/mcp-map')
from sai_mcp_map.server import app
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=5004, log_level="warning")
