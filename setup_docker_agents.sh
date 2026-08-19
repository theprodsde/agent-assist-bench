#!/bin/bash
# Setup: Build and run real agent frameworks from external repos

set -e

echo "============================================================"
echo "AgentAssistBench — Docker Agent Setup (From Source)"
echo "============================================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    echo -e "${RED}✗ Docker daemon is not running${NC}"
    echo "  Please start Docker and try again"
    exit 1
fi
echo -e "${GREEN}✓ Docker is running${NC}"

# Check external repos exist
echo ""
echo "Step 1: Verifying external repositories..."

if [ ! -d "external/hermes-agent" ]; then
    echo -e "${RED}✗ Missing external/hermes-agent${NC}"
    exit 1
fi
echo -e "${GREEN}✓ external/hermes-agent found${NC}"

if [ ! -d "external/openclaw" ]; then
    echo -e "${RED}✗ Missing external/openclaw${NC}"
    exit 1
fi
echo -e "${GREEN}✓ external/openclaw found${NC}"

# Step 2: Build Docker images from source
echo ""
echo "Step 2: Building Docker images from source..."
echo "  (This may take 10-20 minutes on first build)"
echo ""

docker compose build --no-cache

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Docker images built successfully${NC}"
else
    echo -e "${RED}✗ Docker build failed${NC}"
    echo "  Check output above for errors"
    exit 1
fi

# Step 3: Stop existing containers
echo ""
echo "Step 3: Stopping existing containers (if any)..."
docker compose down 2>/dev/null || true
echo -e "${GREEN}✓ Ready to start${NC}"

# Step 4: Start containers
echo ""
echo "Step 4: Starting agent containers..."
docker compose up -d

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Containers started${NC}"
else
    echo -e "${RED}✗ Failed to start containers${NC}"
    echo "  Check logs: docker compose logs"
    exit 1
fi

# Step 5: Wait for startup
echo ""
echo "Step 5: Waiting for agents to start (60 seconds)..."
sleep 60

# Step 6: Test endpoints
echo ""
echo "Step 6: Testing agent endpoints..."
echo ""

HERMES_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/health || echo "000")
OPENCLAW_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/health || echo "000")

if [ "$HERMES_HEALTH" = "200" ]; then
    echo -e "${GREEN}✓ Hermes healthy${NC}"
else
    echo -e "${YELLOW}⚠ Hermes not responding (status: $HERMES_HEALTH)${NC}"
fi

if [ "$OPENCLAW_HEALTH" = "200" ]; then
    echo -e "${GREEN}✓ OpenClaw healthy${NC}"
else
    echo -e "${YELLOW}⚠ OpenClaw not responding (status: $OPENCLAW_HEALTH)${NC}"
fi

# Step 7: Run Python test
echo ""
echo "Step 7: Running detailed agent tests..."
python test_agents.py

echo ""
echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "You are now running REAL agent frameworks in Docker:"
echo "  - Hermes: http://localhost:8001 (NousResearch)"
echo "  - OpenClaw: http://localhost:8002 (OpenClaw)"
echo ""
echo "Next steps:"
echo "  1. Verify agents are responding: python test_agents.py"
echo "  2. Configure benchmark:"
echo "     export BENCH_HERMES_ENDPOINT=http://localhost:8001"
echo "     export BENCH_OPENCLAW_ENDPOINT=http://localhost:8002"
echo "  3. Run benchmark: aab run \"Your test prompt\""
echo ""
echo "View logs:"
echo "  docker compose logs -f hermes"
echo "  docker compose logs -f openclaw"
echo ""
echo "Stop containers:"
echo "  docker compose down"
