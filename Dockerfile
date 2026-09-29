FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./

# Keep dependency installation cached when only application source changes.
RUN python -c 'import subprocess, tomllib; deps = tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]; subprocess.check_call(["pip", "install", "--no-cache-dir", *deps])'

COPY README.md ./
COPY src ./src

RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=base /usr/local/bin/jerico /usr/local/bin/jerico
COPY --from=base /app /app

RUN useradd --create-home jerico \
    && mkdir -p /app/data \
    && chown jerico:jerico /app/data
USER jerico

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["jerico", "serve", "--host", "0.0.0.0", "--port", "8000"]
