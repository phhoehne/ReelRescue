# Changelog

## 1.1.0 — Unreleased

- Recovery from damaged VCD/SVCD discs is the main app flow.
- Combine saved raw disc reads using sector addresses and EDC checksums.
- Show recovered tracks, verified sectors and remaining uncertainty.
- Review recovered tracks, then optionally clean up picture and sound or export H.264/H.265 copies.
- Add a native Xcode project with signing configuration.
- Add shared app versioning and local release packaging with SHA-256 checksums.

This is the first planned public release. Current local packages are ad-hoc signed;
Developer ID signing and notarization are pending.
