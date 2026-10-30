FROM public.ecr.aws/docker/library/python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system --gid 10001 mechanics \
    && useradd --system --uid 10001 --gid mechanics --home-dir /app mechanics

COPY pyproject.toml README.md ./
COPY src ./src
COPY deploy/docker-entrypoint.sh /usr/local/bin/mechanics-entrypoint

RUN pip install --no-cache-dir \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        . \
    && chmod 0755 /usr/local/bin/mechanics-entrypoint \
    && chown -R mechanics:mechanics /app

USER mechanics

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/mechanics-entrypoint"]
CMD ["python", "-m", "mechanics_agent.main"]
