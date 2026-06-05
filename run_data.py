import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'servers/mcp-data')
from sai_mcp_data.server import app
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=5002, log_level="warning")
