FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 JOBPILOT_DATA_DIR=/data
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend
COPY extension extension

RUN useradd --create-home --uid 1000 jobpilot && mkdir -p /data && chown jobpilot /data
USER jobpilot

WORKDIR /app/backend
EXPOSE 8000
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health')"
# --forwarded-allow-ips='*' so cookies are marked Secure behind the host's HTTPS proxy
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
