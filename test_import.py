import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'servers/mcp-gis')

try:
    import sai_mcp_gis.tools.spatial_query as sq
    print("spatial_query OK")
except Exception as e:
    print(f"spatial_query FAIL: {e}")

try:
    import sai_mcp_gis.tools.vector_io as vio
    print("vector_io OK")
except Exception as e:
    print(f"vector_io FAIL: {e}")

try:
    from sai_mcp_gis.server import app
    print("server OK, tools:", len(app.routes))
except Exception as e:
    print(f"server FAIL: {e}")
