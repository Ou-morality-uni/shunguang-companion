FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SHUNGUANG_MODE=server \
    SHUNGUANG_DATA_DIR=/data SHUNGUANG_MASTER_KEY_FILE=/run/secrets/master.key \
    SHUNGUANG_LAN_MODE=1 HOME=/tmp XDG_CACHE_HOME=/tmp/cache
WORKDIR /app
COPY app/backend/requirements.lock.txt /tmp/requirements.txt
ARG PIP_SOURCE=official
RUN case "$PIP_SOURCE" in \
      official) pip_index=https://pypi.org/simple ;; \
      tencent) pip_index=https://mirrors.cloud.tencent.com/pypi/simple ;; \
      aliyun) pip_index=https://mirrors.aliyun.com/pypi/simple ;; \
      *) echo 'Unknown package source. Choose official, tencent or aliyun.'; exit 2 ;; \
    esac \
    && pip install --no-cache-dir --timeout 30 --retries 2 --index-url "$pip_index" -r /tmp/requirements.txt && pip check \
    && groupadd -g 10001 shunguang && useradd -u 10001 -g 10001 -M shunguang
COPY app/ /app/
USER 10001:10001
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-access-log", "--timeout-graceful-shutdown", "20"]
