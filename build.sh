#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
xcodebuild -project "$PROJECT_DIR/ReelRescue.xcodeproj" -scheme ReelRescue \
  -configuration Release -derivedDataPath "$PROJECT_DIR/build/DerivedData" build "$@"
mkdir -p "$PROJECT_DIR/dist"
ditto "$PROJECT_DIR/build/DerivedData/Build/Products/Release/Reel Rescue.app" "$PROJECT_DIR/dist/Reel Rescue.app"
codesign --verify --deep --strict "$PROJECT_DIR/dist/Reel Rescue.app"
printf 'Built %s\n' "$PROJECT_DIR/dist/Reel Rescue.app"
