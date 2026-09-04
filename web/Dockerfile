FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY web/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY web/app /app/app
RUN mkdir -p /data
EXPOSE 9487
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; req=urllib.request.Request('http://127.0.0.1:9487/api/health',headers={'Authorization':'Bearer '+os.environ['PVE_FAN_WEB_TOKEN']}); urllib.request.urlopen(req,timeout=3).read()" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9487", "--workers", "1"]
