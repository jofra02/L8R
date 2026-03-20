#!/bin/bash
set -e

echo "==> Running database migrations..."
python -m alembic upgrade head

echo "==> Initializing Qdrant collections..."
python -m src.utils.init_qdrant

echo "==> Starting application server..."
if [ "$APP_ENV" = "production" ]; then
    exec gunicorn src.api.app:app \
        -k uvicorn.workers.UvicornWorker \
        --workers "${UVICORN_WORKERS:-2}" \
        --bind 0.0.0.0:8000
else
    exec uvicorn src.api.app:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers "${UVICORN_WORKERS:-1}"
fi
