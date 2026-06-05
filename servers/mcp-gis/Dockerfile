FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libproj-dev libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY servers/mcp-gis/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sai/ /app/sai/
COPY servers/mcp-gis/sai_mcp_gis/ /app/sai_mcp_gis/

CMD ["uvicorn", "sai_mcp_gis.server:app", "--host", "0.0.0.0", "--port", "5000"]
