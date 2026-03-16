#!/bin/bash
# BitoGuard API Testing Script using Newman (Postman CLI)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "BitoGuard API Testing with Postman/Newman"
echo "=========================================="
echo ""

# Check if Newman is installed
if ! command -v newman &> /dev/null; then
    echo -e "${YELLOW}Newman (Postman CLI) is not installed.${NC}"
    echo "Installing Newman globally..."
    npm install -g newman
    echo ""
fi

# Check if API server is running
echo "Checking if BitoGuard API is running..."
if ! curl -s http://127.0.0.1:8001/healthz > /dev/null 2>&1; then
    echo -e "${RED}ERROR: BitoGuard API is not running on http://127.0.0.1:8001${NC}"
    echo ""
    echo "Please start the API server first:"
    echo "  cd bitoguard_core"
    echo "  source .venv/bin/activate"
    echo "  PYTHONPATH=. uvicorn api.main:app --reload --port 8001"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ API server is running${NC}"
echo ""

# Set environment variables
export BASE_URL="${BASE_URL:-http://127.0.0.1:8001}"
export API_KEY="${BITOGUARD_API_KEY:-test-api-key}"

echo "Test Configuration:"
echo "  Base URL: $BASE_URL"
echo "  API Key: ${API_KEY:0:10}..."
echo ""

# Run Newman with the collection
echo "Running Postman collection tests..."
echo "=========================================="
echo ""

newman run "$PROJECT_ROOT/postman_collection.json" \
    --env-var "BASE_URL=$BASE_URL" \
    --env-var "API_KEY=$API_KEY" \
    --reporters cli,json \
    --reporter-json-export "$PROJECT_ROOT/newman-results.json" \
    --color on \
    --timeout-request 30000 \
    --bail

TEST_EXIT_CODE=$?

echo ""
echo "=========================================="

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All API tests passed!${NC}"
    echo ""
    echo "Test results saved to: newman-results.json"
else
    echo -e "${RED}✗ Some API tests failed${NC}"
    echo ""
    echo "Check newman-results.json for detailed failure information"
    exit 1
fi

echo ""
echo "Test Summary:"
echo "  Collection: BitoGuard Core API"
echo "  Results: newman-results.json"
echo ""
