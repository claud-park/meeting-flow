#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title 타임블록 검토
# @raycast.mode silent
# @raycast.packageName Meeting Flow

# Optional parameters:
# @raycast.icon 📅

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/review-open.sh"
