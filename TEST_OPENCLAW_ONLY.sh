#!/bin/bash
# Test OpenClaw agent in Docker - Step by step

set -e

echo "============================================================"
echo "OPENCLAW AGENT TEST - Docker Isolation"
echo "============================================================"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}Step 1: Stop any existing containers${NC}"
docker compose down 2>/dev/null || true
sleep 2

echo ""
echo -e "${BLUE}Step 2: Build OpenClaw image from source${NC}"
echo "  (This may take 15-20 minutes first time)"
docker compose build openclaw --no-cache

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}✗ Build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Build complete${NC}"

echo ""
echo -e "${BLUE}Step 3: Start only OpenClaw container${NC}"
docker compose up openclaw -d

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}✗ Failed to start${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Container started${NC}"

echo ""
echo -e "${BLUE}Step 4: Check container is running${NC}"
docker ps | grep openclaw-agent
echo -e "${GREEN}✓ Container is running${NC}"

echo ""
echo -e "${BLUE}Step 5: Wait for OpenClaw to initialize (90 seconds)${NC}"
echo "  OpenClaw initializes plugins, gateway, and models..."
for i in {90..1}; do
    echo -n "."
    sleep 1
done
echo ""
echo -e "${GREEN}✓ Initialization time elapsed${NC}"

echo ""
echo -e "${BLUE}Step 6: Check container logs${NC}"
echo "  (Looking for 'listening' or 'gateway started' messages)"
echo "---"
docker compose logs openclaw | tail -20
echo "---"

echo ""
echo -e "${BLUE}Step 7: Check health endpoint${NC}"
HEALTH=$(curl -s -w "\nHTTP_STATUS:%{http_code}" http://localhost:8002/health)
STATUS=$(echo "$HEALTH" | grep "HTTP_STATUS:" | cut -d: -f2)
BODY=$(echo "$HEALTH" | grep -v "HTTP_STATUS:")

echo "  URL: http://localhost:8002/health"
echo "  Status: $STATUS"
echo "  Response:"
echo "$BODY" | head -10

if [ "$STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Health check passed${NC}"
else
    echo -e "${YELLOW}⚠ Health check returned status $STATUS${NC}"
    echo "  Container may still be initializing..."
fi

echo ""
echo -e "${BLUE}Step 8: Send a test request to OpenClaw${NC}"
echo "  (Simple 'Hello' prompt to verify API works)"
echo ""

REQUEST_BODY='{
  "model": "openclaw",
  "messages": [
    {
      "role": "user",
      "content": "Say hello in one word"
    }
  ],
  "max_tokens": 50,
  "temperature": 0.5
}'

echo "Request URL: POST http://localhost:8002/v1/chat/completions"
echo "Request body:"
echo "$REQUEST_BODY" | jq . 2>/dev/null || echo "$REQUEST_BODY"
echo ""

RESPONSE=$(curl -s -w "\n\nHTTP_STATUS:%{http_code}" \
  -X POST http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${BENCH_OPENCLAW_API_KEY:-changeme}" \
  -d "$REQUEST_BODY")

RESPONSE_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS:" | cut -d: -f2)
RESPONSE_BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS:")

echo "Response Status: $RESPONSE_STATUS"
echo ""
echo "Response Body:"
echo "$RESPONSE_BODY" | jq . 2>/dev/null || echo "$RESPONSE_BODY"

if [ "$RESPONSE_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ API request successful!${NC}"

    # Extract the actual response
    MESSAGE=$(echo "$RESPONSE_BODY" | jq -r '.choices[0].message.content' 2>/dev/null || echo "")
    if [ ! -z "$MESSAGE" ]; then
        echo ""
        echo "OpenClaw Response:"
        echo "  $MESSAGE"
    fi
else
    echo -e "${YELLOW}⚠ API request returned status $RESPONSE_STATUS${NC}"
fi

echo ""
echo "============================================================"
echo "OPENCLAW TEST COMPLETE"
echo "============================================================"
echo ""
echo "Comparison with Hermes:"
echo "  - How did OpenClaw respond differently?"
echo "  - What quality/style differences do you notice?"
echo "  - Which response was better for your use case?"
echo ""
echo "Next steps:"
echo "  1. Compare both responses"
echo "  2. Review response times and quality"
echo "  3. Run full benchmark with both: aab run \"test prompt\""
echo ""
echo "View live logs:"
echo "  docker compose logs -f openclaw"
echo ""
echo "Stop container:"
echo "  docker compose down"
