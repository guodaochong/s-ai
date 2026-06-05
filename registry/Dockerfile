FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sai/ /app/sai/

CMD ["uvicorn", "sai.registry.server:app", "--host", "0.0.0.0", "--port", "9000"]
