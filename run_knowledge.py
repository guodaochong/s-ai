import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'servers/mcp-knowledge')
from sai_mcp_knowledge.server import app
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=5003, log_level="warning")
