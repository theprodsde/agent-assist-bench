# Hermes Agent — official Docker image from NousResearch
# https://github.com/nousresearch/hermes-agent
#
# Uses the official nousresearch/hermes-agent image which bundles
# Python 3.13, Node.js 22, Playwright, and all dependencies.
#
# The image is stateless — all config lives in /opt/data (mounted volume).
#
# Build:  docker build -t hermes-bench -f docker/hermes/Dockerfile .
# Run:    docker run -d -p 8001:8642 -v $(pwd)/docker/hermes/data:/opt/data --env-file docker/hermes/.env hermes-bench
# Test:   curl http://localhost:8001/health

FROM nousresearch/hermes-agent:latest

# Copy pre-built config into the data volume seed directory
# These get seeded into /opt/data on first boot if not already present
COPY config.yaml /opt/seed/config.yaml
