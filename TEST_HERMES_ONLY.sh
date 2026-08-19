#!/bin/bash
# Test Hermes agent in Docker - Step by step

set -e

echo "============================================================"
echo "HERMES AGENT TEST - Docker Isolation"
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
echo -e "${BLUE}Step 2: Build Hermes image from source${NC}"
echo "  (This may take 10-15 minutes first time)"
docker compose build hermes --no-cache

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}✗ Build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Build complete${NC}"

echo ""
echo -e "${BLUE}Step 3: Start only Hermes container${NC}"
docker compose up hermes -d

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}✗ Failed to start${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Container started${NC}"

echo ""
echo -e "${BLUE}Step 4: Check container is running${NC}"
docker ps | grep hermes-agent
echo -e "${GREEN}✓ Container is running${NC}"

echo ""
echo -e "${BLUE}Step 5: Wait for Hermes to initialize (60 seconds)${NC}"
echo "  Hermes compiles toolsets and loads models on startup..."
for i in {60..1}; do
    echo -n "."
    sleep 1
done
echo ""
echo -e "${GREEN}✓ Initialization time elapsed${NC}"

echo ""
echo -e "${BLUE}Step 6: Check container logs${NC}"
echo "  (Looking for 'listening' or 'gateway started' messages)"
echo "---"
docker compose logs hermes | tail -20
echo "---"

echo ""
echo -e "${BLUE}Step 7: Check health endpoint${NC}"
HEALTH=$(curl -s -w "\nHTTP_STATUS:%{http_code}" http://localhost:8001/health)
STATUS=$(echo "$HEALTH" | grep "HTTP_STATUS:" | cut -d: -f2)
BODY=$(echo "$HEALTH" | grep -v "HTTP_STATUS:")

echo "  URL: http://localhost:8001/health"
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
echo -e "${BLUE}Step 8: Send a test request to Hermes${NC}"
echo "  (Simple 'Hello' prompt to verify API works)"
echo ""

REQUEST_BODY='{
  "model": "hermes",
  "messages": [
    {
      "role": "user",
      "content": "Say hello in one word"
    }
  ],
  "max_tokens": 50,
  "temperature": 0.5
}'

echo "Request URL: POST http://localhost:8001/v1/chat/completions"
echo "Request body:"
echo "$REQUEST_BODY" | jq . 2>/dev/null || echo "$REQUEST_BODY"
echo ""

RESPONSE=$(curl -s -w "\n\nHTTP_STATUS:%{http_code}" \
  -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${BENCH_HERMES_API_KEY:-changeme}" \
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
        echo "Hermes Response:"
        echo "  $MESSAGE"
    fi
else
    echo -e "${YELLOW}⚠ API request returned status $RESPONSE_STATUS${NC}"
fi

echo ""
echo "============================================================"
echo "HERMES TEST COMPLETE"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Review the response above"
echo "  2. Verify Hermes is responding correctly"
echo "  3. When ready, test OpenClaw with: bash TEST_OPENCLAW_ONLY.sh"
echo "  4. Then run full benchmark: aab run \"test prompt\""
echo ""
echo "View live logs:"
echo "  docker compose logs -f hermes"
echo ""
echo "Stop container:"
echo "  docker compose down"
