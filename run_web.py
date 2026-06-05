import sys
sys.path.insert(0, '.')
from web.server import app
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=3000, log_level="info")
