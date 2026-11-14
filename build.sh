#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
xcodebuild -project "$PROJECT_DIR/ReelRescue.xcodeproj" -scheme ReelRescue \
  -configuration Release -derivedDataPath "$PROJECT_DIR/build/DerivedData" build "$@"
mkdir -p "$PROJECT_DIR/dist"
STAGING="$(mktemp -d "$PROJECT_DIR/dist/.package.XXXXXX")"
ditto "$PROJECT_DIR/build/DerivedData/Build/Products/Release/Reel Rescue.app" "$STAGING/Reel Rescue.app"
codesign --verify --deep --strict "$STAGING/Reel Rescue.app"
if [ -d "$PROJECT_DIR/dist/Reel Rescue.app" ]; then
  mv "$PROJECT_DIR/dist/Reel Rescue.app" "$STAGING/previous.app"
fi
mv "$STAGING/Reel Rescue.app" "$PROJECT_DIR/dist/Reel Rescue.app"
rm -rf "$STAGING"
printf 'Built %s\n' "$PROJECT_DIR/dist/Reel Rescue.app"
