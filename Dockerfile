FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Tạo thư mục cần thiết
RUN mkdir -p logs data

# Expose dashboard port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/bot/status')" || exit 1

CMD ["python", "main.py"]
