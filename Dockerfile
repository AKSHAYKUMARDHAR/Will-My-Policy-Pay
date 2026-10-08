FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fineprint ./fineprint
COPY api ./api
COPY web ./web
COPY data/catalogue.json data/documents.json ./data/
# Hosts such as Hugging Face Spaces run the container as a non-root user: keep the event log writable
RUN mkdir -p data/logs && chmod 777 data/logs
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
