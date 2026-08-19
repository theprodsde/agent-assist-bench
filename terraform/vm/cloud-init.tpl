#!/bin/bash
# Cloud-init template for agent VM provisioning.
# This script runs on first boot to configure the agent service.

set -euo pipefail

# Install Docker (runtime for agent container)
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Pull and run the agent container
# The API key is fetched from the referenced secret store at runtime.
# In production, use a managed identity or instance metadata to retrieve
# the secret value from the vault rather than embedding it.
docker run -d \
  --name ${agent_name} \
  --restart unless-stopped \
  -p ${agent_port}:${agent_port} \
  -e AGENT_PORT=${agent_port} \
  -e API_KEY_SECRET_REF=${api_key_secret_ref} \
  ${agent_name}:latest
