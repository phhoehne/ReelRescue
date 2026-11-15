# Changelog

## 1.1.0 — Unreleased

- Repair presentation-only MPEG timestamp jumps when decode timestamps remain valid.

- Normalize damaged MPEG timestamps before joining and verify picture/audio payload preservation.
- Allow selecting existing MPEG tracks for post-processing without another CD read.

- Fix CD progress parsing when ddrescue includes an open-ended raw-device map tail.

- Show a live CD-reading progress bar, percentage, bytes read and adaptive ETA.

- Recover original MPEG tracks as the only extraction result, preserving MPEG-2 on SVCDs and MPEG-1 on VCDs.
- Discard temporary working files at the end of each run; remove persistent recovery-data and diagnostic storage.
- Keep enhancement and lossless track joining in post-processing.
- Use one recovery screen for an inserted CD or saved raw disc reads.
- Detect optical media reported with current macOS WholeDisk metadata.
- Automatically load recovered footage in the enhancement screen.
- Bundle the Python runtime, FFmpeg/ffprobe, codecs and ddrescue; no Homebrew setup is required.
- Include third-party licenses, matching dependency sources and Developer ID signing support.

This is the first planned public release. Local test builds are reviewed before
release packaging and notarization.
