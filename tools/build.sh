#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Keep the developer's ignored sdkconfig and build directory intact.
# IDF_PATH must point to ESP-IDF 6.0.2, with export.sh already sourced.
: "${IDF_PATH:?Source ESP-IDF 6.0.2 export.sh first}"
exec "${IDF_PYTHON_ENV_PATH:?Activate the ESP-IDF Python environment}/bin/python" "$IDF_PATH/tools/idf.py" -B build/usb-v2 -D SDKCONFIG="$PWD/build/usb-v2/sdkconfig" build
