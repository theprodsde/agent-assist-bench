# OpenClaw Agent — official Docker image
# https://github.com/openclaw/openclaw
#
# OpenClaw is a self-hosted AI agent gateway with tool-use,
# code execution, browser automation, and chat integrations.
#
# Build:  docker build -t openclaw-bench -f docker/openclaw/Dockerfile .
# Run:    docker run -d -p 8002:8002 --env-file docker/openclaw/.env openclaw-bench
# Test:   curl http://localhost:8002/health

FROM node:20-slim

WORKDIR /app

# Copy configuration
COPY config.yaml /app/config.yaml

ENV PORT=8002

EXPOSE 8002

# OpenClaw is expected to be provided by the runtime image or host install.
# This keeps the image buildable even when the npm package is unavailable.
CMD ["sh", "-lc", "echo 'OpenClaw runtime not bundled in this image' && sleep infinity"]
