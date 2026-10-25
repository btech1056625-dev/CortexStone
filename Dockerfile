FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY src ./src

RUN python -m pip install --no-cache-dir ".[postgres,embeddings]"

ENV HOME=/home/cortexstone \
    HF_HOME=/home/cortexstone/.cache/huggingface \
    XDG_CACHE_HOME=/home/cortexstone/.cache

RUN mkdir -p /home/cortexstone/.cache/huggingface \
    && chown -R 10001:10001 /home/cortexstone

USER 10001:10001

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "cortexstone.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
