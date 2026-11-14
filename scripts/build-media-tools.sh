#!/bin/bash
# Developer-only source build. End users receive the resulting app bundle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/build/vendor"
PREFIX="$VENDOR/prefix"
export MACOSX_DEPLOYMENT_TARGET=14.0
export PATH="$VENDOR/tools/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
JOBS="$(sysctl -n hw.logicalcpu)"
cd "$VENDOR/src/x264-stable"
./configure --prefix="$PREFIX" --enable-static --disable-cli --disable-opencl --extra-cflags='-mmacosx-version-min=14.0'
make -j"$JOBS"
make install
cmake -S "$VENDOR/src/x265_4.1/source" -B "$VENDOR/x265-build" \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DENABLE_SHARED=OFF -DENABLE_CLI=OFF \
  -DENABLE_ASSEMBLY=OFF -DENABLE_LIBNUMA=OFF
cmake --build "$VENDOR/x265-build" -j "$JOBS"
cmake --install "$VENDOR/x265-build"
cd "$VENDOR/src/ffmpeg-8.0.1"
./configure --prefix="$PREFIX" --arch=arm64 --cc=clang \
  --enable-static --disable-shared --disable-autodetect --disable-network \
  --disable-ffplay --disable-doc --disable-debug --enable-gpl --enable-version3 \
  --enable-videotoolbox --enable-audiotoolbox --enable-libx264 --enable-libx265 \
  --pkg-config-flags=--static --extra-cflags="-I$PREFIX/include -mmacosx-version-min=14.0" \
  --extra-ldflags="-L$PREFIX/lib -mmacosx-version-min=14.0" --extra-libs=-lc++
make -j"$JOBS"
make install
cd "$VENDOR/src/ddrescue-1.30"
./configure --prefix="$PREFIX" CXX=clang++ CXXFLAGS='-O2 -mmacosx-version-min=14.0'
make -j"$JOBS"
make install
mkdir -p "$VENDOR/payload/bin"
cp "$PREFIX/bin/ffmpeg" "$PREFIX/bin/ffprobe" "$PREFIX/bin/ddrescue" "$VENDOR/payload/bin/"
