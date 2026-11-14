# Reel Rescue

### Recover memories from damaged discs.

Reel Rescue is an open-source macOS app for recovering footage from damaged **Video CDs (VCDs)** and **Super Video CDs (SVCDs)**—including discs that will no longer mount or play normally.

It reads recorded CDs, compares saved raw reads of the same disc, and saves the recovered MPEG video tracks. Once the footage is saved, optional tools improve picture clarity and sound or create a more compact viewing copy.

**Recover the footage first, then enhance it if needed.**

## What it does

- **Recover from a physical CD** using GNU ddrescue with the disc’s actual raw sector size and a temporary working map.
- **Combine multiple disc reads** by recorded sector address and EDC checksum, retaining intact data found across different attempts.
- **Retry uncertain sectors** with two bounded read passes when recovering from an inserted CD.
- **Find VCD/SVCD video tracks** from the disc directory, with a single-file CUE sheet as a fallback when the directory is damaged.
- **Preserve the authored video:** recover the original MPEG program streams without converting the picture or sound.
- **Report remaining damage:** the app flags uncertain recovery data while processing.
- **Keep recovery separate from enhancement:** recovery outputs one original `.mpg` file per video track.

Original disc media and source files are opened read-only. Each run saves its videos in a new output folder. Processing stays on your Mac, with no accounts or uploads.

## Optional footage enhancement

These tools are available in **Enhance footage** after recovery:

- Combine compatible recovered tracks into one MPEG video without re-encoding.
- Gentle noise reduction and restrained sharpening.
- Deinterlacing for sources marked as interlaced.
- Audio click reduction in manually selected time ranges.
- Short, manually selected holds of the last intact frame to cover a damaged moment.
- H.264 viewing copies at the original display size or 1080p.
- Smaller 1080p H.265/HEVC copies, with hardware encoding when available.
- A 10-second picture preview before committing to a longer export.

The app preserves the picture’s proportions when upscaling. It uses no generative face reconstruction, beauty filters, or invented voices. Enhancement is off by default. AAC audio is copied without re-encoding when compatible and no audio repair is requested; full exports using that path verify the copied audio against the source.

## Download and run

Download the app ZIP from the project's GitHub Releases, extract it, and move
**Reel Rescue.app** into Applications. Requires an Apple Silicon Mac running
macOS 14 or later. Older macOS versions have not yet been tested on hardware.

**No Homebrew, Python installation, or Terminal setup is required.** The app
includes its recovery engine, FFmpeg, ffprobe, video encoders and GNU ddrescue.
All processing runs locally. A compatible optical drive is needed only when
recovering from a physical CD; saved raw disc images work without one.

Help & setup reports built-in tool availability. If a tool is missing or cannot
start, reinstall the complete app download. Source builds require the developer
setup below, which is separate from installing the app.

This is an early project built from a real damaged-disc recovery workflow.
Physical capture needs broader testing across drives and damaged media.

## Recover your footage

### From a damaged CD

1. Open Reel Rescue and select **Recover footage → CD drive**.
2. Insert a recorded VCD or SVCD and refresh the drive list.
3. Optionally add earlier raw reads of that same physical disc.
4. Choose where to save the recovery project and click **Start recovery**.

During **Reading the CD**, the app shows a progress bar, percentage, bytes read,
and estimated time remaining. The estimate adapts to the recent read speed;
it switches to **Waiting for drive** during stalls on damaged areas. The ETA
covers the current CD-reading pass, rather than the later recovery steps.

Only compatible whole, read-only optical media are accepted. If macOS denies raw-device access, the app reports the error. You can still work with previously saved raw images.

### From saved disc reads

1. Select **Recover footage → Local files**.
2. Add one or more whole-disc raw `.bin` or `.iso` images from the **same physical disc**.
3. Add the original single-file CUE sheet if the app cannot read the track directory.
4. Choose an output folder and click **Start recovery**.

An `.iso` extension alone does not identify the sector format. Recovery currently requires raw **2,352-byte CD sectors**.

### Enhance recovered footage

Recovery finishes with one `.mpg` video per authored track. There are no format,
enhancement, or joining options in the extraction step. SVCD footage retains
MPEG-2; VCD footage retains MPEG-1. Damage that could not be recovered may remain.

Open **Enhance footage** to work on the latest recovered track. When there are
multiple tracks, **Combine recovered tracks** joins them in disc order into
`Combined.mpg` without re-encoding. Tracks must have matching picture and sound
formats; incompatible tracks are left separate. Picture/sound improvements and
H.264/H.265 viewing copies are separate post-processing actions.

## Saved files

**The only extraction results are the recovered videos:**

```text
Reel Rescue <date>/
  Track_01.mpg
  Track_02.mpg
  Track_03.mpg
```

The app does not retain raw images, maps, logs, reports, checksums, or summary
files as user results or in app-managed recovery storage. Working data is held
in a temporary directory and removed when the run completes, fails, or is
cancelled. Video tracks already saved successfully remain available. Abrupt
process termination may leave operating-system temporary files for normal OS
cleanup. Original source images and the physical disc are never deleted.

MPEG video is preserved exactly as extracted. Some players handle MP4 more
conveniently; make a separate viewing copy in Enhance footage when needed.
See [the user guide](Guide.txt) for post-processing options and limitations.

## Supported formats and limits

| Input | Support |
| --- | --- |
| Compatible recorded VCD/SVCD in an optical drive | Raw 2,352-byte sectors required |
| Whole-disc raw CD images | Supported, including raw images named `.iso` |
| Single-file Mode 2/2352 CUE sheet | Track-boundary fallback |
| Extracted video files readable by FFmpeg | Optional enhancement and export |
| Ordinary 2,048-byte ISO images | Not supported for disc recovery |
| DVDs, Blu-rays, and general hard-drive recovery | Not supported |
| Multi-file CUE layouts | Not supported |

Recovery cannot recreate data that was never successfully read. Sector checksums provide evidence about recovered data; passing checksums or playback validation does not guarantee a visually or audibly perfect recording. Mode 2 sector address bytes are not protected by EDC. When recovering only from images, unavailable trailing sectors cannot always be identified.

Missing sound cannot be faithfully restored by click reduction, and frame holds conceal a defect by repeating existing footage. They do not reconstruct the missing moment. Review important scenes yourself, and retain your original reads and recovered source footage.

## Development

```text
ReelRescue.xcodeproj/   Native macOS app target and shared scheme
native/                SwiftUI interface, AVPlayerView preview, icon and app metadata
backend/               Python recovery engine and C checksum accelerator
scripts/               Xcode engine-packaging step
Config/                Signing configuration and local override example
tests/                 Recovery and video-processing tests
Guide.txt              User instructions
```

### Build from source (developers only)

Install Xcode, official python.org Python **3.12.10**, and pkg-config. Prepare the
pinned runtime once, then build through Xcode or the command line:

```sh
python3.12 scripts/prepare-runtime.py
./build.sh
open "dist/Reel Rescue.app"
```

Preparation downloads checksum-pinned upstream sources and installs isolated
build tools under `build/vendor/`. It compiles the media tools for macOS 14 arm64.
Xcode freezes the recovery engine with its Python runtime, embeds all tools and
licenses, checks for external-library paths and signs nested code. Subsequent
source edits are automatically included by the packaging phase. A Python
checksum fallback is available if the accelerator cannot be loaded.

Run the tests from the repository folder:

```sh
python3 -m unittest discover -s tests -v
```

Tests cover checksum validation, sector merging, conflict reporting, device guards, cancellation, repair ranges, picture geometry, chapters, audio preservation, and HEVC output. They create synthetic fixtures and do not require personal footage.

Generated builds, private media, recovery images, test outputs, and personal signing settings are excluded from Git.

## Signing and distribution

For development signing, copy `Config/Developer.xcconfig.example` to `Config/Developer.xcconfig`, then set your Apple development team, signing identity, and a bundle identifier registered to your team. The local override is ignored by Git. You can also configure signing in the target’s **Signing & Capabilities** settings.

Xcode signs the app and its embedded checksum library. Hardened Runtime is enabled. App Sandbox is disabled because recovery accesses raw optical media and invokes embedded processing tools.

Use **Product → Archive** for a release archive. Distribution outside your own Mac requires the appropriate signing configuration and, for Developer ID distribution, notarization. The default ad-hoc build is not a notarized public release. The runtime tools are included in the app.

Publish the matching dependency-source ZIP alongside the app ZIP. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for component licenses and corresponding-source materials.

### Notarize a signed release

Store notarization credentials in Keychain interactively (never in source or chat):

```sh
xcrun notarytool store-credentials ReelRescue
```

Configure a Developer ID Application identity in your ignored local signing
configuration, then package committed source with `python3 scripts/release.py`.
Submit that ZIP to Apple and verify the stapled result:

```sh
python3 scripts/notarize.py --profile ReelRescue
```

The command uploads the app to Apple, waits for acceptance, staples the ticket,
checks Gatekeeper, and regenerates the final ZIP and its checksum. If Apple’s
ticket-delivery DNS lookup fails, an HTTPS fallback can retrieve the issued
ticket without changing network settings; Gatekeeper must still accept it. It preserves
the submitted ZIP for audit. Publish the final versioned app ZIP, matching dependency-source ZIP, SHA256SUMS.txt and
release.json as the GitHub release assets. No GitHub publication occurs.

## Versions and release downloads

The app uses `MAJOR.MINOR.PATCH` versions, starting with **1.1.0**:

- **Patch:** fixes that preserve existing behavior and formats.
- **Minor:** new features that preserve compatibility.
- **Major:** breaking changes to supported workflows or saved project formats.

A separate, increasing build number identifies every packaged revision. Both
values live in `Config/Version.xcconfig` and appear in Xcode, the app bundle,
and the app sidebar. Never reuse a published version/build pair.

```sh
python3 scripts/version.py          # Show the current version
python3 scripts/version.py patch    # Next bug-fix version; also increments build
python3 scripts/version.py minor    # Next feature version; also increments build
python3 scripts/version.py major    # Next breaking version; also increments build
python3 scripts/version.py build    # Another build of the same app version
```

Distribute app ZIPs as **GitHub Release assets**, rather than committing binaries
to Git. The repository contains source; a release tag such as `v1.1.0` identifies
the source used for that release. Release downloads include the runtime tools.

To prepare a local package:

```sh
python3 scripts/release.py
```

This builds the app and creates a versioned app ZIP, a matching dependency-source ZIP, `SHA256SUMS.txt`, and
`release.json` under `dist/v<version>/build-<number>/`. Metadata records the source
commit, uncommitted-change status, signing type and required tools. Packaging
never creates a Git tag, uploads a file, or publishes a release. Existing
archives are not overwritten.

Before publishing, update [CHANGELOG.md](CHANGELOG.md), commit the final source,
and package from a clean working tree. For a public Mac download, complete
Developer ID signing and notarization first. Tag that commit with the matching
`vMAJOR.MINOR.PATCH` version, then attach the app ZIP, dependency-source ZIP, checksum and metadata to its
GitHub Release. A package marked `source_dirty: true` is a local preview and
should be rebuilt from committed source before publication.

## Contributing

Bug reports, reproducible recovery cases, and focused pull requests are welcome. Useful reports include the macOS version, optical drive model when relevant, input sector format, and the error shown in Task details. Remove private paths and personal information before sharing errors; avoid posting personal footage or full disc images publicly.

For recovery-engine changes, include a synthetic fixture or test where practical. Contributions are made under the project’s MIT license.

## License

Reel Rescue is licensed under the [MIT License](LICENSE). External tools retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
