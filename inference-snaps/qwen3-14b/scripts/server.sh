#!/bin/bash

set -euo pipefail

engine="$(modelctl status --wait-for-components --format=json | jq -r .engine)"
exec modelctl run --wait-for-components -- "$SNAP/engines/$engine/server" "$@"
