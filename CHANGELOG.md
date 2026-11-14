# Changelog

## 1.1.0 — Unreleased

- Bundle the recovery engine, Python runtime, FFmpeg/ffprobe and ddrescue.
- Remove Homebrew and Terminal setup from the end-user flow.
- Build bundled media tools for macOS 14 arm64; include licenses and matching source archives.

- Unify CD drive and local file recovery on one screen.
- Fix detection of optical media reported with macOS WholeDisk metadata.
- Refresh inserted media automatically and explain unsupported media or inspection failures.

- Recovery from damaged VCD/SVCD discs is the main app flow.
- Combine saved raw disc reads using sector addresses and EDC checksums.
- Show recovered tracks, verified sectors and remaining uncertainty.
- Review recovered tracks, then optionally clean up picture and sound or export H.264/H.265 copies.
- Add a native Xcode project with signing configuration.
- Add shared app versioning and local release packaging with SHA-256 checksums.

This is the first planned public release. Developer ID signing is configured locally. Each final build is notarized and
verified separately before publication.
