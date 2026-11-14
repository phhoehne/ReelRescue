# Bundled components

Reel Rescue's own source code, checksum accelerator and original icon are MIT
licensed. The app distributes the following separate tools and runtime components:

| Component | Version | License |
| --- | --- | --- |
| FFmpeg / ffprobe | 8.0.1, GPL-enabled static build | GPL-3.0-or-later |
| x264 | Stable source archive pinned by SHA-256 | GPL-2.0-or-later |
| x265 | 4.1 | GPL-2.0-or-later |
| GNU ddrescue | 1.30 | GPL-2.0-or-later |
| CPython runtime | 3.12.10, official macOS framework | Python Software Foundation License and bundled notices |
| OpenSSL (inside Python runtime) | 3.0.16 | Apache-2.0 |
| PyInstaller bootloader / runtime hooks | 6.16.0 | GPL-2.0-or-later with bootloader exception |

The MIT license does not relicense these components. FFmpeg, ffprobe and ddrescue
are invoked as separate executables. FFmpeg statically incorporates x264/x265.
Python is packaged into the recovery executable using PyInstaller's bootloader
exception. Build tools such as CMake are used during development and not shipped.

License texts are included in the app at Contents/Resources/runtime/licenses.
Exact upstream source archives, SHA-256 hashes and build recipes are packaged in
ReelRescue-<version>-build<number>-dependency-sources.zip. **Publish this source ZIP
alongside every corresponding binary release**, with SHA256SUMS.txt and release.json.
The source ZIP provides the corresponding-source materials for bundled GPL tools;
users may modify and rebuild them under their respective licenses.

Pinned source URLs and archive hashes are in Config/RuntimeSources.json. Rebuild
instructions and recipes are included in the source ZIP and the repository.
Upstream archives are unmodified; relocation/signing changes are made only during
packaging. Apple's system libraries and frameworks are supplied by macOS and
remain subject to Apple's applicable terms.
