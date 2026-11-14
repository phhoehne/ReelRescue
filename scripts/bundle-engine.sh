#!/bin/bash
set -euo pipefail
ENGINE_DIR="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/backend"
mkdir -p "$ENGINE_DIR"
cp "$SRCROOT/backend/reel_rescue.py" "$ENGINE_DIR/reel_rescue.py"
xcrun clang -arch arm64 -mmacosx-version-min=14.0 -O3 -dynamiclib \
  "$SRCROOT/backend/edc.c" -o "$ENGINE_DIR/edc.dylib"
if [ "${CODE_SIGNING_ALLOWED:-NO}" = YES ]; then
  codesign --force --sign "${EXPANDED_CODE_SIGN_IDENTITY:--}" --timestamp=none "$ENGINE_DIR/edc.dylib"
fi
