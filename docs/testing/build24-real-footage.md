# Build 24: real-footage export acceptance

Local test build: Reel Rescue 1.1.0 (24). **80 of 80 full-length scenarios passed, producing 158 verified video files.** This is a local test build, not a published or notarized release.

Three recovered PAL MPEG-2 tracks were used in every scenario: 7,572, 25,205 and 8,627 decoded source frames (41,404 total, approximately 27 minutes 37 seconds). The original files remained unchanged. The same bundled engine and media tools were used throughout; their hashes were checked again at completion.

## Export faults corrected

- Individual MPEG exports now prepare damaged timestamps using the same compressed-payload-preserving process as combined exports. Duration validation uses that prepared timeline, avoiding a false failure before the named file is saved.
- Frame-hold repairs now use the normalized input time origin, preserving the opening picture and its alignment with sound.
- Equal or backward video timestamps are advanced to the next millisecond before encoding. Every decoded frame is retained.
- Overlapping decoded audio blocks now receive nonoverlapping timestamps before AAC encoding. Decoded samples and forward gaps are preserved; the correction does not resample audio or change voices.

Each fault has a regression test. All 29 engine regression tests passed. The local app’s code signature was verified after the acceptance run.

## Checks performed

- Full cross product of MP4/MOV/MKV, H.264/H.265, original display size/720p/1080p, separate/combined output and gentle enhancement off/on: 72 scenarios.
- Original MPEG output, separate and combined: two scenarios.
- Six additional full-length scenarios exercise audio repair, frame holds and both together across containers and codecs.
- Every re-encoded video passed the app’s validation and a second independent full decode with errors treated as failures. Checks include dimensions, codec, audio presence, duration, decoded frame count where no frame holds were requested, and picture/sound start alignment.
- Separate original-MPEG outputs were byte-identical to the inputs. Combined original-MPEG output retained identical compressed payloads. These preservation modes retain damage already present in the source.
- Requested filenames and the exact destination folder were verified for every output. No extra files or nested output folders were accepted.
- The actual SwiftUI Name editor was tested while still focused, through to full-length separate and combined outputs from the packaged engine. Names with spaces, accents, punctuation, version dots, literal `_preview`, and supplied extensions were covered. No separate naming fault was reproduced. Earlier export failures prevented the named result from being published.
- Existing-file protection, invalid names, cancellation cleanup and an unwritable destination were checked. The relocated packaged runtime passed without Homebrew or host Python/tool fallback.

These are automated full-file checks, not a claim that every video was manually watched. Damaged source footage can still contain visible or audible defects.

## Complete scenario results

All scenarios used all three full input tracks. Separate output produces three videos; combined output produces one. “Source” means 768 × 576 display size for these anamorphic 480 × 576 inputs. HD options produce 1280 × 720 or 1920 × 1080 with the source aspect ratio preserved.

| ID | Output | Container | Codec | Size | Gentle enhancement | Repairs | Videos | Result |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 001 | Separate | MPEG | Original MPEG-2 | Original | Off | None | 3 | Passed |
| 002 | Combined | MPEG | Original MPEG-2 | Original | Off | None | 1 | Passed |
| 003 | Combined | MP4 | H.264 | Source | Off | None | 1 | Passed |
| 004 | Combined | MOV | H.264 | Source | Off | None | 1 | Passed |
| 005 | Combined | MKV | H.264 | Source | Off | None | 1 | Passed |
| 006 | Combined | MP4 | H.265 | Source | Off | None | 1 | Passed |
| 007 | Combined | MOV | H.265 | Source | Off | None | 1 | Passed |
| 008 | Combined | MKV | H.265 | Source | Off | None | 1 | Passed |
| 009 | Combined | MP4 | H.264 | 720p | Off | None | 1 | Passed |
| 010 | Combined | MOV | H.264 | 720p | Off | None | 1 | Passed |
| 011 | Combined | MKV | H.264 | 720p | Off | None | 1 | Passed |
| 012 | Combined | MP4 | H.265 | 720p | Off | None | 1 | Passed |
| 013 | Combined | MOV | H.265 | 720p | Off | None | 1 | Passed |
| 014 | Combined | MKV | H.265 | 720p | Off | None | 1 | Passed |
| 015 | Combined | MP4 | H.264 | 1080p | Off | None | 1 | Passed |
| 016 | Combined | MOV | H.264 | 1080p | Off | None | 1 | Passed |
| 017 | Combined | MKV | H.264 | 1080p | Off | None | 1 | Passed |
| 018 | Combined | MP4 | H.265 | 1080p | Off | None | 1 | Passed |
| 019 | Combined | MOV | H.265 | 1080p | Off | None | 1 | Passed |
| 020 | Combined | MKV | H.265 | 1080p | Off | None | 1 | Passed |
| 021 | Combined | MP4 | H.264 | Source | On | None | 1 | Passed |
| 022 | Combined | MOV | H.264 | Source | On | None | 1 | Passed |
| 023 | Combined | MKV | H.264 | Source | On | None | 1 | Passed |
| 024 | Combined | MP4 | H.265 | Source | On | None | 1 | Passed |
| 025 | Combined | MOV | H.265 | Source | On | None | 1 | Passed |
| 026 | Combined | MKV | H.265 | Source | On | None | 1 | Passed |
| 027 | Combined | MP4 | H.264 | 720p | On | None | 1 | Passed |
| 028 | Combined | MOV | H.264 | 720p | On | None | 1 | Passed |
| 029 | Combined | MKV | H.264 | 720p | On | None | 1 | Passed |
| 030 | Combined | MP4 | H.265 | 720p | On | None | 1 | Passed |
| 031 | Combined | MOV | H.265 | 720p | On | None | 1 | Passed |
| 032 | Combined | MKV | H.265 | 720p | On | None | 1 | Passed |
| 033 | Combined | MP4 | H.264 | 1080p | On | None | 1 | Passed |
| 034 | Combined | MOV | H.264 | 1080p | On | None | 1 | Passed |
| 035 | Combined | MKV | H.264 | 1080p | On | None | 1 | Passed |
| 036 | Combined | MP4 | H.265 | 1080p | On | None | 1 | Passed |
| 037 | Combined | MOV | H.265 | 1080p | On | None | 1 | Passed |
| 038 | Combined | MKV | H.265 | 1080p | On | None | 1 | Passed |
| 039 | Separate | MP4 | H.264 | Source | Off | None | 3 | Passed |
| 040 | Separate | MOV | H.264 | Source | Off | None | 3 | Passed |
| 041 | Separate | MKV | H.264 | Source | Off | None | 3 | Passed |
| 042 | Separate | MP4 | H.265 | Source | Off | None | 3 | Passed |
| 043 | Separate | MOV | H.265 | Source | Off | None | 3 | Passed |
| 044 | Separate | MKV | H.265 | Source | Off | None | 3 | Passed |
| 045 | Separate | MP4 | H.264 | 720p | Off | None | 3 | Passed |
| 046 | Separate | MOV | H.264 | 720p | Off | None | 3 | Passed |
| 047 | Separate | MKV | H.264 | 720p | Off | None | 3 | Passed |
| 048 | Separate | MP4 | H.265 | 720p | Off | None | 3 | Passed |
| 049 | Separate | MOV | H.265 | 720p | Off | None | 3 | Passed |
| 050 | Separate | MKV | H.265 | 720p | Off | None | 3 | Passed |
| 051 | Separate | MP4 | H.264 | 1080p | Off | None | 3 | Passed |
| 052 | Separate | MOV | H.264 | 1080p | Off | None | 3 | Passed |
| 053 | Separate | MKV | H.264 | 1080p | Off | None | 3 | Passed |
| 054 | Separate | MP4 | H.265 | 1080p | Off | None | 3 | Passed |
| 055 | Separate | MOV | H.265 | 1080p | Off | None | 3 | Passed |
| 056 | Separate | MKV | H.265 | 1080p | Off | None | 3 | Passed |
| 057 | Separate | MP4 | H.264 | Source | On | None | 3 | Passed |
| 058 | Separate | MOV | H.264 | Source | On | None | 3 | Passed |
| 059 | Separate | MKV | H.264 | Source | On | None | 3 | Passed |
| 060 | Separate | MP4 | H.265 | Source | On | None | 3 | Passed |
| 061 | Separate | MOV | H.265 | Source | On | None | 3 | Passed |
| 062 | Separate | MKV | H.265 | Source | On | None | 3 | Passed |
| 063 | Separate | MP4 | H.264 | 720p | On | None | 3 | Passed |
| 064 | Separate | MOV | H.264 | 720p | On | None | 3 | Passed |
| 065 | Separate | MKV | H.264 | 720p | On | None | 3 | Passed |
| 066 | Separate | MP4 | H.265 | 720p | On | None | 3 | Passed |
| 067 | Separate | MOV | H.265 | 720p | On | None | 3 | Passed |
| 068 | Separate | MKV | H.265 | 720p | On | None | 3 | Passed |
| 069 | Separate | MP4 | H.264 | 1080p | On | None | 3 | Passed |
| 070 | Separate | MOV | H.264 | 1080p | On | None | 3 | Passed |
| 071 | Separate | MKV | H.264 | 1080p | On | None | 3 | Passed |
| 072 | Separate | MP4 | H.265 | 1080p | On | None | 3 | Passed |
| 073 | Separate | MOV | H.265 | 1080p | On | None | 3 | Passed |
| 074 | Separate | MKV | H.265 | 1080p | On | None | 3 | Passed |
| 075 | Combined | MP4 | H.265 | 1080p | On | Audio | 1 | Passed |
| 076 | Separate | MKV | H.264 | 720p | On | Frame hold | 3 | Passed |
| 077 | Combined | MOV | H.265 | Source | On | Audio, Frame hold | 1 | Passed |
| 078 | Combined | MKV | H.265 | 720p | On | Audio, Frame hold | 1 | Passed |
| 079 | Separate | MKV | H.265 | Source | On | Audio | 3 | Passed |
| 080 | Combined | MKV | H.264 | 720p | On | Audio | 1 | Passed |

## Reproducibility

The reusable commands are documented in the README. Private run manifests, per-scenario events, saved-file hashes, decoder logs and safety/name-editor results are kept under the ignored `build/acceptance/build24/` directory. Personal footage and test videos are not committed. Case 036 retains one validated combined MP4/H.265 1080p output named `Custom wedding name.mp4` for local inspection.

Bundled-tool SHA-256 values:

| Component | SHA-256 |
| --- | --- |
| Engine | `bfab4c08813f3df6df2b126b6158a573971ad249f06aed1b0504985690de790c` |
| FFmpeg | `c8e4b6c9d820fb37058f07b36ee5224ad5413d09b4914438e7e8192c437eee6f` |
| FFprobe | `11dd5c002ed29f6963a31742b45918b71338b6562ab10a42c8c0cb051a6d2e86` |
