# Changelog

## 1.1.0 — Unreleased

- Correct overlapping decoded-audio timestamps before AAC encoding, preserving samples and forward gaps while preventing Matroska validation failures.

- Repair duplicate or backward presentation timestamps before encoding, retaining every frame and preventing Matroska playback-validation failures.

- Normalize individual recovered MPEG timelines before re-encoding, verify unchanged compressed data, and prevent false duration-change failures.
- Validate decoded frame counts for interlaced viewing copies as well as progressive ones.

- Keep frame-hold repairs on the normalized output timeline so MPEG start offsets do not discard the opening picture or delay it against audio.

- Replace export presets with explicit container, codec and resolution controls, plus an approximate total output-size range.
- Add numeric percentage and adaptive remaining-time estimates for joining, rendering and playback validation.

- Preserve MP4 timestamp precision during playback validation so valid combined H.264/H.265 videos are saved instead of falsely rejected as decoding errors.

- Show the actual saved output path on completion and select the created video files with Show in Finder.

- Default enhancement to all newly recovered tracks, remember their locations across app launches, and allow switching to other footage or back to the recovered videos.

- Unify enhancement and joining into one workflow with ordered inputs, separate/combined output, explicit names, and one Create action.
- Save post-processing videos directly in the chosen folder, with no generated subfolder and no overwriting.

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
