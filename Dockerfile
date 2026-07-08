FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

# Web GUI
EXPOSE 8000
# Forza Data Out telemetry (UDP)
EXPOSE 5300/udp

# Default: serve the live dashboard. Override for `mcp`, `record`, etc.
CMD ["python", "main.py", "gui", "--no-browser"]
