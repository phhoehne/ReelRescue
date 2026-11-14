import SwiftUI
import AppKit
import AVKit
import UniformTypeIdentifiers

private let ink = Color(red: 0.09, green: 0.20, blue: 0.29)
private let accent = Color(red: 0.0, green: 0.43, blue: 0.48)
private let mist = Color(red: 0.94, green: 0.96, blue: 0.97)

enum Workflow: String, CaseIterable {
    case disc = "From a damaged CD"
    case images = "From saved disc reads"
    case video = "Clean up & share"
    var key: String { switch self { case .video: return "video"; case .images: return "images"; case .disc: return "disc" } }
    var symbol: String { switch self { case .video: return "film"; case .images: return "square.stack.3d.up"; case .disc: return "opticaldisc" } }
}

final class Model: ObservableObject {
    @Published var workflow: Workflow = .disc
    @Published var sources: [URL] = []
    @Published var cue: URL?
    @Published var destination = FileManager.default.urls(for: .moviesDirectory, in: .userDomainMask).first!
    @Published var preset = "native"
    @Published var enhance = false
    @Published var retry = true
    @Published var makeVideos = true
    @Published var audioRanges = ""
    @Published var holdRanges = ""
    @Published var previewStart = "0:00"
    @Published var busy = false
    @Published var phase = "Ready when you are"
    @Published var detail = "Insert your damaged CD, or choose saved disc reads."
    @Published var fraction: Double?
    @Published var warning = ""
    @Published var error = ""
    @Published var log = ""
    @Published var project: URL?
    @Published var result: URL?
    @Published var recoveredVideos: [URL] = []
    @Published var selectedRecoveredVideo = ""
    @Published var recoveryVerified: Int?
    @Published var recoveryUncertain = 0
    @Published var player: AVPlayer?
    @Published var tools: [String: String] = [:]
    @Published var dependencyMessage = "Checking local tools…"
    @Published var drives: [[String: Any]] = []
    @Published var selectedDrive = ""
    @Published var refreshing = false
    @Published var showHelp = false
    @Published var showLog = false
    var process: Process?
    var python: String?
    var backend: String { Bundle.main.resourceURL!.appendingPathComponent("backend/reel_rescue.py").path }
    var ready: Bool { python != nil && tools["ffmpeg"] != nil && tools["ffprobe"] != nil }
    var canRun: Bool {
        ready && !busy && (workflow == .disc ? !selectedDrive.isEmpty && tools["ddrescue"] != nil : !sources.isEmpty)
    }

    init() {
        let fm = FileManager.default
        let candidates = ["/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        python = candidates.first(where: fm.isExecutableFile(atPath:))
        if !fm.fileExists(atPath: destination.path) { destination = fm.homeDirectoryForCurrentUser.appendingPathComponent("Desktop") }
        checkTools()
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "--demo-video"), i + 1 < args.count {
            workflow = .video
            add([URL(fileURLWithPath: args[i+1])])
        }
        if let i = args.firstIndex(of: "--demo-destination"), i + 1 < args.count {
            destination = URL(fileURLWithPath: args[i+1])
        }
        if workflow == .disc { refreshDrives() }
    }

    func selectWorkflow(_ next: Workflow, video: URL? = nil) {
        guard !busy else { return }
        player?.pause(); player = nil; sources = []; cue = nil; result = nil
        audioRanges = ""; holdRanges = ""; error = ""; warning = ""; fraction = nil
        recoveryVerified = nil; recoveryUncertain = 0; recoveredVideos = []; selectedRecoveredVideo = ""
        workflow = next; phase = "Ready when you are"
        detail = next == .video ? "Choose recovered footage to review, clean up or share." : "Choose a source to start recovering your footage."
        if let video { add([video]) }
        if next == .disc { refreshDrives() }
    }

    func reviewRecovered() {
        guard let url = recoveredVideos.first(where: { $0.path == selectedRecoveredVideo }) else { return }
        selectWorkflow(.video, video: url)
    }

    func invoke(_ args: [String], completion: @escaping (Data) -> Void) {
        guard let py = python else { return }
        let script = backend
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process(), pipe = Pipe()
            p.executableURL = URL(fileURLWithPath: py); p.arguments = [script] + args
            p.standardOutput = pipe; p.standardError = FileHandle.nullDevice
            do {
                try p.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                DispatchQueue.main.async { completion(data) }
            } catch { DispatchQueue.main.async { completion(Data()) } }
        }
    }

    func checkTools() {
        guard python != nil else { dependencyMessage = "Python 3 is missing. Open Help for setup."; return }
        invoke(["doctor"]) { data in
            guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let found = obj["tools"] as? [String: Any] else {
                self.dependencyMessage = "Could not start the recovery engine. Open Help for setup."; return
            }
            self.tools = found.compactMapValues { $0 as? String }
            self.dependencyMessage = self.ready ? "Video tools are ready" : "FFmpeg or ffprobe is missing. Open Help for setup."
        }
    }

    func refreshDrives() {
        guard python != nil else { refreshing = false; return }
        refreshing = true
        invoke(["discs"]) { data in
            self.drives = (try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]) ?? []
            self.selectedDrive = self.drives.first?["device"] as? String ?? ""
            self.refreshing = false
        }
    }

    func chooseSource() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.allowsMultipleSelection = workflow != .video
        panel.message = workflow == .video ? "Choose an original or recovered video." : "Choose raw CD images from the same disc. Their extension may be .bin or .iso."
        panel.prompt = "Choose"
        if workflow == .video { panel.allowedContentTypes = [.movie, .video, UTType(filenameExtension: "mkv") ?? .data, UTType(filenameExtension: "mpg") ?? .data] }
        if panel.runModal() == .OK { add(panel.urls) }
    }

    func add(_ urls: [URL]) {
        guard !busy else { return }
        if workflow == .video {
            if let first = urls.first { sources = [first]; player = AVPlayer(url: first) }
        } else {
            for url in urls {
                if url.pathExtension.lowercased() == "cue" { cue = url }
                else if !sources.contains(url) { sources.append(url) }
            }
        }
        error = ""; result = nil; recoveryVerified = nil; recoveredVideos = []
        detail = workflow == .video ? "Review your footage, then choose any cleanup or sharing options." : "Your disc reads are ready to compare."
    }

    func chooseCue() {
        let p = NSOpenPanel(); p.allowedContentTypes = [UTType(filenameExtension: "cue") ?? .data]
        if p.runModal() == .OK { cue = p.url }
    }

    func chooseDestination() {
        let p = NSOpenPanel(); p.canChooseFiles = false; p.canChooseDirectories = true; p.canCreateDirectories = true
        p.directoryURL = destination; p.prompt = "Save projects here"
        if p.runModal() == .OK, let url = p.url { destination = url }
    }

    func start(preview: Bool = false) {
        guard canRun, let py = python else { return }
        player?.pause(); busy = true; phase = "Preparing"; detail = "Creating a separate output project"
        error = ""; warning = ""; log = ""; fraction = nil; project = nil; result = nil
        recoveryVerified = nil; recoveryUncertain = 0; recoveredVideos = []; selectedRecoveredVideo = ""
        var settings: [String: Any] = ["mode": workflow.key, "sources": sources.map(\.path), "destination": destination.path,
                                      "preset": preset, "enhance": enhance, "retry": retry, "export": makeVideos,
                                      "audio_ranges": audioRanges, "hold_ranges": holdRanges, "preview_start": previewStart,
                                      "preview": preview, "hardware": true]
        if let cue { settings["cue"] = cue.path }
        if workflow == .disc {
            settings["device"] = selectedDrive
            settings["device_identity"] = drives.first(where: { $0["device"] as? String == selectedDrive })?["identity"]
        }
        let request = FileManager.default.temporaryDirectory.appendingPathComponent("reel-rescue-\(UUID().uuidString).json")
        do { try JSONSerialization.data(withJSONObject: settings, options: .prettyPrinted).write(to: request) }
        catch { self.error = error.localizedDescription; busy = false; return }
        let p = Process(), output = Pipe()
        p.executableURL = URL(fileURLWithPath: py); p.arguments = [backend, "job", request.path]
        p.standardOutput = output; p.standardError = output
        p.environment = ProcessInfo.processInfo.environment.merging(["PYTHONUNBUFFERED": "1", "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"]) { _, v in v }
        process = p
        do { try p.run() }
        catch { self.error = error.localizedDescription; busy = false; process = nil; return }
        DispatchQueue.global(qos: .userInitiated).async {
            var buffer = Data()
            while true {
                let chunk = output.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                while let newline = buffer.firstIndex(of: 10) {
                    let line = buffer.subdata(in: 0..<newline); buffer.removeSubrange(0...newline)
                    DispatchQueue.main.async { self.receive(line) }
                }
            }
            if !buffer.isEmpty { let tail = buffer; DispatchQueue.main.async { self.receive(tail) } }
            p.waitUntilExit(); try? FileManager.default.removeItem(at: request)
            DispatchQueue.main.async {
                self.busy = false; self.process = nil
                if self.result == nil && self.error.isEmpty && self.phase != "Stopped" {
                    self.error = "The task ended before a verified result was produced. Open the project folder to inspect the logs."
                    self.phase = "Needs attention"
                }
            }
        }
    }

    func receive(_ data: Data) {
        guard let e = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let type = e["type"] as? String else {
            if let text = String(data: data, encoding: .utf8) { log += text + "\n" }; return
        }
        if let message = e["message"] as? String { log += message + "\n" }
        switch type {
        case "project": project = (e["path"] as? String).map { URL(fileURLWithPath: $0) }
        case "progress":
            phase = e["phase"] as? String ?? phase; detail = e["detail"] as? String ?? ""; fraction = e["fraction"] as? Double
        case "warning": warning = e["message"] as? String ?? ""
        case "recovery":
            let good = e["verified"] as? Int ?? 0, total = e["total"] as? Int ?? 0
            recoveryVerified = good; recoveryUncertain = e["uncertain"] as? Int ?? 0
            log += "Verified \(good.formatted()) of \(total.formatted()) sectors.\n"
        case "complete":
            phase = workflow == .video ? "Viewing copy ready" : "Recovery finished"; fraction = 1
            result = (e["path"] as? String).map { URL(fileURLWithPath: $0) }
            if workflow != .video, let report = e["report"] as? [String: Any] {
                let copies = report["outputs"] as? [[String: Any]] ?? []
                let originals = report["extracted"] as? [[String: Any]] ?? []
                recoveredVideos = (copies.isEmpty ? originals : copies).compactMap { ($0["file"] as? String).map { URL(fileURLWithPath: $0) } }
                selectedRecoveredVideo = recoveredVideos.first?.path ?? ""
                detail = "Your recovered image, original footage and recovery report are saved."
            } else { detail = "Your viewing copy and validation report are saved in the new project folder." }
        case "cancelled": phase = "Stopped"; detail = e["message"] as? String ?? ""; fraction = nil
        case "error": phase = "Needs attention"; error = e["message"] as? String ?? "The task failed."; fraction = nil
        default: break
        }
        if log.count > 30000 { log = String(log.suffix(30000)) }
    }

    func stop() { if process?.isRunning == true { phase = "Stopping safely"; process?.terminate() } }
    func revealProject() { if let project { NSWorkspace.shared.open(project) } }
    func playResult() { if let result { NSWorkspace.shared.open(result) } }
}

struct NativeVideoPlayer: NSViewRepresentable {
    let player: AVPlayer
    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.player = player
        view.controlsStyle = .floating
        view.videoGravity = .resizeAspect
        view.showsFullScreenToggleButton = true
        return view
    }
    func updateNSView(_ view: AVPlayerView, context: Context) {
        if view.player !== player { view.player = player }
    }
}

struct ContentView: View {
    @EnvironmentObject var m: Model
    @State private var dropActive = false
    @State private var repairsExpanded = false
    @State private var copiesExpanded = false
    @State private var earlierReadsExpanded = false

    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 225)
            Divider()
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        header
                        if m.workflow != .video { recoveryOverview }
                        sourceArea
                        if m.workflow != .video && m.result != nil { recoveryResults }
                        options
                        destination
                    }.padding(30).frame(maxWidth: .infinity, alignment: .leading)
                }.disabled(m.busy)
                statusBar
            }.background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(minWidth: 960, minHeight: 740)
        .tint(accent)
        .sheet(isPresented: $m.showHelp) { help }
        .sheet(isPresented: $m.showLog) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Task details").font(.title2.bold())
                ScrollView { Text(m.log.isEmpty ? "No messages yet." : m.log).textSelection(.enabled).font(.system(.body, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading) }
                HStack { if m.project != nil { Button("Open project folder", action: m.revealProject) }; Spacer(); Button("Done") { m.showLog = false }.keyboardShortcut(.defaultAction) }
            }.padding(24).frame(width: 700, height: 480)
        }
    }

    var sidebar: some View {
        VStack(alignment: .leading, spacing: 26) {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: "opticaldisc").font(.system(size: 43)).foregroundStyle(accent)
                Text("Reel Rescue").font(.system(size: 23, weight: .semibold, design: .rounded)).foregroundStyle(ink)
                Text("Recover memories\nfrom damaged discs.").font(.callout).foregroundStyle(.secondary).lineSpacing(3)
            }.padding(.top, 22)
            VStack(spacing: 6) {
                ForEach(Workflow.allCases, id: \.self) { workflow in
                    if workflow == .disc {
                        Text("Recover footage").font(.caption.weight(.semibold)).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 12).padding(.bottom, 6)
                    }
                    if workflow == .video {
                        Divider().padding(.vertical, 15)
                        Text("After recovery").font(.caption.weight(.semibold)).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 12).padding(.bottom, 6)
                    }
                    Button { m.selectWorkflow(workflow) } label: {
                        HStack(spacing: 10) {
                            Image(systemName: workflow.symbol).frame(width: 20)
                            Text(workflow.rawValue).font(.system(size: 13, weight: m.workflow == workflow ? .semibold : .regular))
                            Spacer(minLength: 0)
                        }.padding(.horizontal, 12).padding(.vertical, 13)
                            .foregroundStyle(m.workflow == workflow ? accent : ink)
                            .background(m.workflow == workflow ? Color.white : Color.clear, in: RoundedRectangle(cornerRadius: 9))
                    }.buttonStyle(.plain).disabled(m.busy)
                }
            }
            Spacer()
            Label("Processed on your Mac", systemImage: "desktopcomputer").font(.caption).foregroundStyle(.secondary)
            Button { m.showHelp = true } label: { Label("Help & setup", systemImage: "questionmark.circle") }.buttonStyle(.plain)
            Text("Version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"))").font(.caption2).foregroundStyle(.secondary)
        }.padding(20).background(mist)
    }

    var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(m.workflow == .disc ? "Rescue footage from a damaged CD" : m.workflow == .images ? "Recover from saved disc reads" : "Clean up & share recovered footage").font(.system(size: 30, weight: .semibold, design: .rounded)).foregroundStyle(ink)
            Text(m.workflow == .video ? "Review what you recovered. Make optional picture, sound and sharing improvements." : "Bring back footage from damaged Video CDs and Super Video CDs—even when they won’t mount or play normally.")
                .font(.body).foregroundStyle(.secondary)
            if !m.ready { Label(m.dependencyMessage, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
        }
    }

    var recoveryOverview: some View {
        HStack(alignment: .top, spacing: 24) {
            recoveryStep("Read safely", "Keep the original disc and source files untouched.", "opticaldisc")
            recoveryStep("Recover more", "Compare saved reads and keep checksum-verified data.", "square.stack.3d.up")
            recoveryStep("See what survived", "Save the footage and identify damage that remains.", "film.stack")
        }.padding(18).background(mist, in: RoundedRectangle(cornerRadius: 10))
    }

    func recoveryStep(_ title: String, _ detail: String, _ icon: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(title, systemImage: icon).font(.callout.weight(.semibold)).foregroundStyle(accent)
            Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    var recoveryResults: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("What we recovered").font(.headline).foregroundStyle(ink)
            Text(m.recoveredVideos.count == 1 ? "1 video track saved" : "\(m.recoveredVideos.count) video tracks saved").font(.title3.weight(.semibold))
            if let verified = m.recoveryVerified {
                Text("\(verified.formatted()) sectors verified · \(m.recoveryUncertain.formatted()) still uncertain").foregroundStyle(.secondary)
            }
            Text("Review the saved footage for visible or audible damage. Cleanup and sharing are optional next steps.").font(.callout).foregroundStyle(.secondary)
            if !m.recoveredVideos.isEmpty {
                Picker("Track to review", selection: $m.selectedRecoveredVideo) {
                    ForEach(m.recoveredVideos, id: \.path) { url in Text(url.lastPathComponent).tag(url.path) }
                }
                Button("Review & clean up this track", action: m.reviewRecovered)
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(mist, in: RoundedRectangle(cornerRadius: 10))
    }

    var sourceArea: some View {
        VStack(alignment: .leading, spacing: 14) {
            if m.workflow == .disc {
                HStack {
                    Label("Inserted VCD / SVCD", systemImage: "opticaldisc").font(.headline)
                    Spacer(); Button(m.refreshing ? "Refreshing…" : "Refresh", action: m.refreshDrives).disabled(m.refreshing)
                }
                if m.drives.isEmpty {
                    Text("Insert your damaged VCD or SVCD, then refresh. You can also recover from saved disc reads without the original CD.")
                        .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    Button("Use saved disc reads instead") { m.selectWorkflow(.images) }
                } else {
                    Picker("CD drive", selection: $m.selectedDrive) {
                        ForEach(m.drives.indices, id: \.self) { i in
                            let d = m.drives[i]
                            Text("\(d["name"] as? String ?? "CD") (\(d["device"] as? String ?? ""))").tag(d["device"] as? String ?? "")
                        }
                    }
                }
            }
            if m.workflow == .disc {
                DisclosureGroup("Add earlier reads of this disc (optional)", isExpanded: $earlierReadsExpanded) {
                    sourceFiles.padding(.top, 12)
                }
            } else { sourceFiles }
        }
    }

    var sourceFiles: some View {
        VStack(alignment: .leading, spacing: 14) {
            if m.workflow == .video, let player = m.player, !m.sources.isEmpty {
                NativeVideoPlayer(player: player).frame(height: 235).background(.black).clipShape(RoundedRectangle(cornerRadius: 9))
                HStack { Image(systemName: "film"); Text(m.sources[0].lastPathComponent).lineLimit(1).truncationMode(.middle); Spacer(); Button("Change video", action: m.chooseSource) }
            } else {
                VStack(spacing: 12) {
                    Image(systemName: m.workflow == .video ? "film.stack" : "opticaldisc").font(.system(size: 32, weight: .light)).foregroundStyle(accent)
                    Text(m.workflow == .video ? "Drop a video here" : m.workflow == .disc ? "Add earlier reads, if you have them" : "Drop images from the same CD here").font(.headline)
                    Text(m.workflow == .video ? "MP4, M4V, MPEG, MOV and other FFmpeg-readable videos" : "Raw .bin or .iso images • optional single-file .cue sheet")
                        .font(.callout).foregroundStyle(.secondary)
                    Button(m.workflow == .video ? "Choose video…" : "Choose images…", action: m.chooseSource).controlSize(.large)
                }.frame(maxWidth: .infinity).padding(24)
                    .background(dropActive ? accent.opacity(0.12) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(accent.opacity(dropActive ? 0.8 : 0.22), style: StrokeStyle(lineWidth: 1, dash: [5,4])))
                    .onDrop(of: [UTType.fileURL.identifier], isTargeted: $dropActive) { providers in
                        for provider in providers {
                            _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                                if let data, let url = URL(dataRepresentation: data, relativeTo: nil) { DispatchQueue.main.async { m.add([url]) } }
                            }
                        }
                        return true
                    }
            }
            if m.workflow != .video {
                ForEach(m.sources, id: \.self) { url in
                    HStack { Image(systemName: "doc"); Text(url.lastPathComponent).lineLimit(1); Spacer(); Button { m.sources.removeAll { $0 == url } } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }.buttonStyle(.plain).help("Remove this source") }
                }
                HStack {
                    Button(m.cue == nil ? "Add CUE sheet…" : "Change CUE sheet…", action: m.chooseCue)
                    if let cue = m.cue { Text(cue.lastPathComponent).font(.caption).lineLimit(1); Button { m.cue = nil } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain) }
                    Spacer()
                }
                Text("Track boundaries are read from the disc directory. A CUE sheet is only needed when that directory is damaged.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    var options: some View {
        VStack(alignment: .leading, spacing: 14) {
            Divider()
            if m.workflow != .video {
                Text("Recovery settings").font(.headline).foregroundStyle(ink)
                if m.workflow == .disc { Toggle("Retry uncertain sectors twice", isOn: $m.retry) }
                Label("Preserve the recovered disc image and original video streams", systemImage: "checkmark.shield").font(.callout)
                Text("Compare reads from the same disc to recover more intact data. Missing or conflicting sectors are listed in your recovery report.").font(.caption).foregroundStyle(.secondary)
                DisclosureGroup("After recovery: make a viewing copy", isExpanded: $copiesExpanded) {
                    VStack(alignment: .leading, spacing: 14) {
                        Toggle("Also create playable videos", isOn: $m.makeVideos)
                        exportOptions.disabled(!m.makeVideos)
                    }.padding(.top, 12)
                }
                Text(m.makeVideos ? "A playable copy will also be made. Cleanup and 1080p sharing options are available above or after recovery." : "Only recovered source footage will be saved. You can make viewing copies later.").font(.caption).foregroundStyle(.secondary)
            } else {
                Text("Optional viewing copy").font(.headline).foregroundStyle(ink)
                exportOptions
                repairOptions
            }
        }
    }

    var exportOptions: some View {
        VStack(alignment: .leading, spacing: 14) {
            Picker("Format", selection: $m.preset) {
                Text("Original display size · H.264").tag("native")
                Text("1080p sharing copy · H.265").tag("share")
                Text("1080p high-quality copy · H.264").tag("hd")
            }.pickerStyle(.menu)
            Text(m.preset == "share" ? "Smaller files, natural appearance. Requires an HEVC-compatible player." : m.preset == "hd" ? "A larger, broadly compatible viewing copy." : "Preserves the source's display size with square pixels.")
                .font(.caption).foregroundStyle(.secondary)
            Toggle("Add gentle noise reduction and sharpening", isOn: $m.enhance)
            Text("Leave this off for footage that is already enhanced. No face reconstruction or beauty filters are used.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    var repairOptions: some View {
                DisclosureGroup("Repair specific moments (optional)", isExpanded: $repairsExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Mark only moments you have reviewed in the player. Use start-end, one range per line. Missing words and pictures cannot be faithfully recreated.").font(.caption).foregroundStyle(.secondary)
                        HStack(alignment: .top, spacing: 18) {
                            VStack(alignment: .leading) {
                                Text("Reduce audio clicks").font(.subheadline.weight(.medium))
                                TextField("01:23.4-01:24.0", text: $m.audioRanges, axis: .vertical).lineLimit(3...4).textFieldStyle(.roundedBorder)
                            }
                            VStack(alignment: .leading) {
                                Text("Hold the last intact frame").font(.subheadline.weight(.medium))
                                TextField("04:44.4-04:45.2", text: $m.holdRanges, axis: .vertical).lineLimit(3...4).textFieldStyle(.roundedBorder)
                                Text("Maximum 2 seconds per hold.").font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }.padding(.top, 10)
                }
    }

    var destination: some View {
        VStack(alignment: .leading, spacing: 9) {
            Divider()
            HStack { Text(m.workflow == .video ? "Save viewing copies in" : "Save recovery projects in").font(.headline); Spacer(); Button("Choose folder…", action: m.chooseDestination) }
            Label(m.destination.path, systemImage: "folder").font(.callout).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            Text("Each run creates a new folder. Source files are never overwritten.").font(.caption).foregroundStyle(.secondary)
        }
    }

    var statusBar: some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
            if !m.error.isEmpty {
                Text(m.error).font(.callout).foregroundStyle(.red).lineLimit(4).textSelection(.enabled)
            }
            if !m.warning.isEmpty {
                Label(m.warning, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange).lineLimit(3)
            }
            HStack(alignment: .center, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(m.phase).font(.headline)
                    Text(m.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    if m.busy {
                        if let f = m.fraction { ProgressView(value: f).frame(maxWidth: 340) }
                        else { ProgressView().controlSize(.small) }
                    }
                }
                Spacer()
                if m.busy { Button("Stop", action: m.stop).controlSize(.large) }
                else if m.result != nil {
                    if m.workflow == .video {
                        Button("Open folder", action: m.revealProject)
                        Button("Play copy", action: m.playResult).buttonStyle(.borderedProminent).controlSize(.large)
                    } else {
                        Button("Open recovery folder", action: m.revealProject).buttonStyle(.borderedProminent).controlSize(.large)
                    }
                    Button(m.workflow == .video ? "New copy" : "New recovery") { m.result = nil; m.recoveryVerified = nil; m.recoveredVideos = []; m.phase = "Ready when you are"; m.detail = "Adjust the settings, then start again." }
                } else {
                    if m.workflow == .video {
                        VStack(spacing: 5) {
                            HStack { Text("From").font(.caption); TextField("0:00", text: $m.previewStart).frame(width: 62).textFieldStyle(.roundedBorder) }
                            Button("Preview 10 seconds") { m.start(preview: true) }
                                .disabled(!m.canRun || !m.audioRanges.isEmpty || !m.holdRanges.isEmpty)
                                .help("Preview picture settings. Clear repair ranges first, or export the full video to review timed repairs.")
                        }
                    }
                    Button(m.workflow == .video ? "Create viewing copy" : "Start recovery") { m.start() }
                        .buttonStyle(.borderedProminent).controlSize(.large).disabled(!m.canRun)
                }
                Button { m.showLog = true } label: { Image(systemName: "text.alignleft") }.help("Task details")
            }
        }.padding(.horizontal, 30).padding(.bottom, 20).padding(.top, 5)
    }

    var help: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Recover footage from damaged discs").font(.system(size: 25, weight: .semibold, design: .rounded)).foregroundStyle(ink)
            Text("Reel Rescue reads damaged VCDs and SVCDs, combines intact data from multiple reads, and saves the footage with a report of remaining damage. Picture cleanup, audio repair and sharing exports are optional steps after recovery.")
            Divider()
            Text("Local tools").font(.headline)
            ForEach(["ffmpeg", "ffprobe", "ddrescue"], id: \.self) { name in
                HStack { Image(systemName: m.tools[name] != nil ? "checkmark.circle.fill" : "exclamationmark.circle").foregroundStyle(m.tools[name] != nil ? accent : .orange); Text(name); Spacer(); Text(m.tools[name] ?? "Not installed").font(.caption).foregroundStyle(.secondary) }
            }
            Text("This personal Mac build uses Python 3 and your installed FFmpeg tools. GNU ddrescue is only needed for reading a physical CD. Tools are not downloaded automatically.").font(.callout).foregroundStyle(.secondary)
            Text("With Homebrew installed, run this in Terminal:").font(.callout)
            Text("brew install python ffmpeg ddrescue").font(.system(.body, design: .monospaced)).textSelection(.enabled).padding(12).frame(maxWidth: .infinity, alignment: .leading).background(mist, in: RoundedRectangle(cornerRadius: 8))
            Text("Recovery accepts whole-disc 2,352-byte raw CD images, even when named .iso. Standard ISO/DVD/Blu-ray images and multi-file CUE layouts are not supported. Combine reads only from the same physical disc.").font(.callout).foregroundStyle(.secondary)
            HStack {
                Button("Recheck tools", action: m.checkTools)
                Button("Open guide") { if let url = Bundle.main.url(forResource: "Guide", withExtension: "txt") { NSWorkspace.shared.open(url) } }
                Spacer(); Button("Done") { m.showHelp = false }.keyboardShortcut(.defaultAction)
            }
        }.padding(28).frame(width: 660)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var model: Model?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let m = Self.model, m.busy {
            let alert = NSAlert(); alert.messageText = "Stop the current task and quit?"
            alert.informativeText = "Originals remain untouched. Partial files and recovery maps will be kept."
            alert.addButton(withTitle: "Keep working"); alert.addButton(withTitle: "Stop and quit")
            if alert.runModal() == .alertFirstButtonReturn { return .terminateCancel }
            m.stop()
        }
        return .terminateNow
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main struct ReelRescueApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject var model = Model()
    var body: some Scene {
        WindowGroup("Reel Rescue") {
            ContentView().environmentObject(model).preferredColorScheme(.light).onAppear { AppDelegate.model = model }
        }.defaultSize(width: 1120, height: 850)
            .commands {
                CommandGroup(replacing: .newItem) { Button("Choose source…", action: model.chooseSource).keyboardShortcut("o").disabled(model.busy) }
                CommandGroup(replacing: .help) { Button("Reel Rescue Help") { model.showHelp = true } }
            }
    }
}
