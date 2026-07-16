#!/bin/bash
# Set DATABASE_URL on Render using API

SERVICE_ID="srv-d997ed1o3t8c73f0eph0"
RENDER_API_KEY="${RENDER_API_KEY}"  # Set this environment variable

if [ -z "$RENDER_API_KEY" ]; then
    echo "ERROR: RENDER_API_KEY not set"
    echo "Get your API key from: https://dashboard.render.com/account/api-tokens"
    exit 1
fi

DATABASE_URL="postgresql://smarthaul_db_wim9_user:wkmOn7vVqtS9k6AbaDRxVNSI47pSAKKX@dpg-d9973h9o3t8c73f003v0-a/smarthaul_db_wim9"

# Update environment variable
curl -X PATCH \
  "https://api.render.com/v1/services/${SERVICE_ID}" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "envVars": [
      {
        "key": "DATABASE_URL",
        "value": "'"${DATABASE_URL}"'"
      }
    ]
  }'

echo ""
echo "Environment variable set. Trigger a manual deploy in Render dashboard."
