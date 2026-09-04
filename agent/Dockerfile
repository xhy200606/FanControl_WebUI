FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PVE_FAN_HOST_NSENTER=1 \
    PVE_FAN_HOST_ETC=/host/etc \
    PVE_FAN_HOST_LIB=/host/usr/local/lib/pve-fan-control

RUN apt-get update && apt-get install -y --no-install-recommends \
      util-linux ipmitool ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agent/app /app/app

EXPOSE 9488
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; req=urllib.request.Request('http://127.0.0.1:9488/api/health',headers={'Authorization':'Bearer '+os.environ['PVE_FAN_AGENT_TOKEN']}); urllib.request.urlopen(req,timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9488", "--workers", "1"]
