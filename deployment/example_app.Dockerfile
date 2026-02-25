FROM alpine:3.23 AS base

RUN apk update && \
    apk add --no-cache python3

RUN python3 -m venv --system-site-packages /usr/local; \
    python3 -m pip install tremolo

WORKDIR /app

ENTRYPOINT ["/usr/bin/env", "--"]
CMD ["sh", "/app/entrypoint.sh"]


# development stage
FROM base AS dev

RUN adduser -Dh /app -u 1000 app app && \
    echo "export PATH=/app/.local/bin:$PATH" > /app/.profile


# production stage
FROM base AS prod

# higher uid and gid!
# this user is not pointed to a normal user on the host
RUN adduser -Dh /app -u 10000 app app && \
    echo "export PATH=/app/.local/bin:$PATH" > /app/.profile
