# Reel Rescue

Recover precious footage from damaged Video CDs and Super Video CDs on macOS.
Read optical media safely, combine intact sectors from multiple raw reads, and
save recovered footage alongside a report of remaining uncertainty. Optional
picture cleanup, targeted sound repairs, and 1080p H.264/H.265 exports follow recovery.

## Requirements

- Apple Silicon Mac, macOS 14 or later; Xcode for building.
- Python 3 and FFmpeg/ffprobe installed separately.
- GNU ddrescue for physical CD capture only.

With Homebrew installed: `brew install python ffmpeg ddrescue`.
All processing is local. No accounts or uploads are required.

## Build and run

Open `ReelRescue.xcodeproj`, select the shared **ReelRescue** scheme, and Run.
Or run `./build.sh`; the app is copied to `dist/Reel Rescue.app`.
Local builds use ad-hoc signing and do not require an Apple development team.
The recovery engine and compiled EDC accelerator are packaged by an Xcode build
phase. Python and FFmpeg executables are not bundled.

## Sign and distribute later

In the app target's **Signing & Capabilities**, choose your Apple team and a
unique bundle identifier. Alternatively copy `Config/Developer.xcconfig.example`
to `Config/Developer.xcconfig` and fill in your team and signing identity; this
personal configuration is ignored by Git. Xcode signs both the app and its
embedded checksum library. Hardened Runtime is enabled; App Sandbox is disabled
because the recovery engine accesses raw optical devices and external tools.

Use Product → Archive for a release archive. Developer ID distribution requires
appropriate Apple certificates, distribution signing, and notarization. No
certificate or team is included, and this repository does not publish anything.
External runtime dependencies must be installed on recipient Macs unless you
add a compliant packaging strategy. See THIRD_PARTY_NOTICES.md before bundling them.

## Development

- `native/ReelRescue.swift`: SwiftUI interface and native video preview.
- `backend/reel_rescue.py`: recovery, export and verification engine.
- `backend/edc.c`: checksum accelerator (Python fallback included).
- `tests/test_engine.py`: focused recovery and video tests.
- `Guide.txt`: user instructions and recovery limits.

Run `python3 -m unittest discover -s tests -v`.
Generated builds, personal signing configuration, private media, recovery images
and test results are excluded from version control. Tests generate their own
fixtures and do not require personal footage.

## Recovery scope

Supports whole-disc 2,352-byte raw VCD/SVCD images and compatible recorded CDs.
Ordinary 2,048-byte ISO images, DVDs, Blu-rays and multi-file CUE layouts are
not currently supported. Recovery cannot recreate footage that was never read;
checksum and playback validation do not guarantee visibly perfect footage.

## License

MIT. See LICENSE. External tools retain their own licenses; see
THIRD_PARTY_NOTICES.md. Contributions are welcome under the same license.
