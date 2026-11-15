import SwiftUI
import Combine
import AppKit
import AVKit
import UniformTypeIdentifiers

private let ink = Color(red: 0.09, green: 0.20, blue: 0.29)
private let accent = Color(red: 0.0, green: 0.43, blue: 0.48)
private let mist = Color(red: 0.94, green: 0.96, blue: 0.97)

enum Workflow: String, CaseIterable {
    case recovery = "Recover footage"
    case video = "Enhance footage"
    var symbol: String { self == .video ? "film" : "opticaldisc" }
}

enum RecoverySource: String, CaseIterable {
    case disc = "CD drive"
    case files = "Local files"
}

final class Model: ObservableObject {
    @Published var workflow: Workflow = .recovery
    @Published var recoverySource: RecoverySource = .disc
    @Published var driveMessage = "Checking for an inserted CD…"
    var usesDrive: Bool { workflow == .recovery && recoverySource == .disc }
    var jobMode: String { workflow == .video ? "video" : usesDrive ? "disc" : "images" }
    @Published var sources: [URL] = []
    @Published var cue: URL?
    @Published var destination = FileManager.default.urls(for: .moviesDirectory, in: .userDomainMask).first!
    @Published var preset = "native"
    @Published var combineOutput = false
    @Published var outputName = "Recovered film"
    private var previousEnhancementSources: [URL] = []
    var outputExtension: String { preset == "original" ? "mpg" : "mp4" }
    var outputBaseName: String {
        let name = outputName.trimmingCharacters(in: .whitespacesAndNewlines)
        return ["mp4", "mpg", "mpeg"].contains((name as NSString).pathExtension.lowercased()) ? (name as NSString).deletingPathExtension : name
    }
    var outputNames: [String] {
        let name = outputBaseName
        return (combineOutput || sources.count <= 1) ? ["\(name).\(outputExtension)"] : sources.indices.map { String(format: "%@_%02d.%@", name, $0 + 1, outputExtension) }
    }
    var outputExists: Bool { outputNames.contains { FileManager.default.fileExists(atPath: destination.appendingPathComponent($0).path) } }
    var validOutputName: Bool {
        let name = outputBaseName
        return !name.isEmpty && ![".", ".."].contains(name) && !name.contains("/") && !name.contains(":") && !name.contains("\\") && !name.contains("\0") && name.utf8.count <= 200
    }
    @Published var enhance = false
    @Published var audioRanges = ""
    @Published var holdRanges = ""
    @Published var previewStart = "0:00"
    @Published var busy = false
    @Published var phase = "Ready"
    @Published var detail = ""
    @Published var fraction: Double?
    @Published var warning = ""
    @Published var error = ""
    @Published var log = ""
    @Published var project: URL?
    @Published var result: URL?
    @Published var savedVideos: [URL] = []
    @Published var recoveredVideos: [URL] = []
    @Published var selectedRecoveredVideo = ""
    @Published var latestRecoveredVideos: [URL] = []
    @Published var latestRecoveredSelection: URL?
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
    private let preferences: UserDefaults
    var process: Process?
    var python: String?
    var bundledEngine: String { Bundle.main.resourceURL!.appendingPathComponent("runtime/engine/ReelRescueEngine").path }
    func engineArguments(_ args: [String]) -> [String] { args }
    var backend: String { Bundle.main.resourceURL!.appendingPathComponent("backend/reel_rescue.py").path }
    var ready: Bool { python != nil && tools["ffmpeg"] != nil && tools["ffprobe"] != nil }
    var canRun: Bool {
        ready && !busy && (workflow != .video || (validOutputName && !outputExists)) && (usesDrive ? !selectedDrive.isEmpty && tools["ddrescue"] != nil : !sources.isEmpty)
    }

    init(preferences: UserDefaults = .standard) {
        self.preferences = preferences
        let fm = FileManager.default
        latestRecoveredVideos = (preferences.stringArray(forKey: "lastRecoveredVideoPaths") ?? [])
            .map { URL(fileURLWithPath: $0) }.filter { fm.fileExists(atPath: $0.path) }
        previousEnhancementSources = latestRecoveredVideos
        latestRecoveredSelection = latestRecoveredVideos.first
        let candidates = [bundledEngine]
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
        if workflow == .recovery { refreshDrives() }
    }

    func selectWorkflow(_ next: Workflow, video: URL? = nil) {
        guard !busy, next != workflow || video != nil else { return }
        if workflow == .recovery, !recoveredVideos.isEmpty {
            latestRecoveredSelection = recoveredVideos.first(where: { $0.path == selectedRecoveredVideo }) ?? recoveredVideos.first
        }
        if workflow == .video { previousEnhancementSources = sources }
        let available = previousEnhancementSources.filter { FileManager.default.fileExists(atPath: $0.path) }
        let recovered = latestRecoveredVideos.filter { FileManager.default.fileExists(atPath: $0.path) }
        let defaultVideos = video.map { [$0] } ?? (!available.isEmpty ? available : recovered)
        player?.pause(); player = nil; sources = []; cue = nil; result = nil; savedVideos = []
        audioRanges = ""; holdRanges = ""; error = ""; warning = ""; fraction = nil
        recoveryVerified = nil; recoveryUncertain = 0; recoveredVideos = []; selectedRecoveredVideo = ""
        workflow = next; phase = "Ready"
        detail = ""
        if next == .video { add(defaultVideos, preserveOrder: true) }
        if next == .recovery { refreshDrives() }
    }

    func reviewRecovered() { selectWorkflow(.video) }

    func useRecoveredVideos() {
        add(latestRecoveredVideos.filter { FileManager.default.fileExists(atPath: $0.path) }, preserveOrder: true)
    }

    func invoke(_ args: [String], completion: @escaping (Data) -> Void) {
        guard let py = python else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process(), pipe = Pipe()
            p.executableURL = URL(fileURLWithPath: py); p.arguments = self.engineArguments(args)
            p.standardOutput = pipe; p.standardError = FileHandle.nullDevice
            do {
                try p.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                DispatchQueue.main.async { completion(data) }
            } catch { DispatchQueue.main.async { completion(Data()) } }
        }
    }

    func checkTools() {
        guard python != nil else { dependencyMessage = "The built-in recovery engine is missing. Reinstall the app."; return }
        invoke(["doctor"]) { data in
            guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let found = obj["tools"] as? [String: Any] else {
                self.dependencyMessage = "Could not start the built-in recovery engine. Reinstall the app."; return
            }
            self.tools = found.compactMapValues { $0 as? String }
            self.dependencyMessage = self.ready ? "Built-in tools are ready" : "A built-in video tool is missing. Reinstall the app."
        }
    }

    func refreshDrives() {
        guard !refreshing, !busy, python != nil else { return }
        refreshing = true
        invoke(["devices"]) { data in
            guard let response = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.drives = []; self.selectedDrive = ""
                self.driveMessage = "Could not inspect the drive. Check Help & setup, then refresh."
                self.refreshing = false
                return
            }
            self.drives = response["discs"] as? [[String: Any]] ?? []
            if !self.drives.contains(where: { $0["device"] as? String == self.selectedDrive }) {
                self.selectedDrive = self.drives.first?["device"] as? String ?? ""
            }
            self.driveMessage = response["message"] as? String ?? ""
            self.refreshing = false
        }
    }

    func changeRecoverySource() {
        result = nil; error = ""; warning = ""; fraction = nil
        recoveryVerified = nil; recoveredVideos = []; phase = "Ready"
        detail = ""
        if recoverySource == .disc { refreshDrives() }
    }

    func chooseSource() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
        panel.message = workflow == .video ? "Choose videos. Compatible MPEG tracks can be combined." : "Choose raw CD images from the same disc. Their extension may be .bin or .iso."
        panel.prompt = "Choose"
        if workflow == .video { panel.allowedContentTypes = [.movie, .video, UTType(filenameExtension: "mkv") ?? .data, UTType(filenameExtension: "mpg") ?? .data] }
        if panel.runModal() == .OK { add(panel.urls, replaceCatalog: workflow == .video) }
    }

    func add(_ urls: [URL], replaceCatalog: Bool = false, preserveOrder: Bool = false) {
        guard !busy else { return }
        if workflow == .video {
            let selected = preserveOrder ? urls : urls.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
            sources = selected
            previousEnhancementSources = selected
            if let first = selected.first { player = AVPlayer(url: first) }
            if selected.count < 2 { combineOutput = false }
        } else {
            for url in urls {
                if url.pathExtension.lowercased() == "cue" { cue = url }
                else if !sources.contains(url) { sources.append(url) }
            }
        }
        error = ""; result = nil; savedVideos = []; recoveryVerified = nil; recoveredVideos = []
        detail = ""
    }

    func chooseCue() {
        let p = NSOpenPanel(); p.allowedContentTypes = [UTType(filenameExtension: "cue") ?? .data]
        if p.runModal() == .OK { cue = p.url }
    }

    func chooseDestination() {
        let p = NSOpenPanel(); p.canChooseFiles = false; p.canChooseDirectories = true; p.canCreateDirectories = true
        p.directoryURL = destination; p.prompt = "Save videos here"
        if p.runModal() == .OK, let url = p.url { destination = url }
    }

    func start(preview: Bool = false) {
        guard canRun, let py = python else { return }
        player?.pause(); busy = true; phase = "Preparing"; detail = ""
        error = ""; warning = ""; log = ""; fraction = nil; project = nil; result = nil; savedVideos = []
        recoveryVerified = nil; recoveryUncertain = 0; recoveredVideos = []; selectedRecoveredVideo = ""
        var settings: [String: Any] = ["mode": jobMode, "sources": sources.map(\.path), "combine": combineOutput, "output_name": outputName, "destination": destination.path,
                                      "preset": preset, "enhance": enhance,
                                      "audio_ranges": audioRanges, "hold_ranges": holdRanges, "preview_start": previewStart,
                                      "preview": preview, "hardware": true]
        if let cue { settings["cue"] = cue.path }
        if usesDrive {
            settings["device"] = selectedDrive
            settings["device_identity"] = drives.first(where: { $0["device"] as? String == selectedDrive })?["identity"]
        }
        let request = FileManager.default.temporaryDirectory.appendingPathComponent("reel-rescue-\(UUID().uuidString).json")
        do { try JSONSerialization.data(withJSONObject: settings, options: .prettyPrinted).write(to: request) }
        catch { self.error = error.localizedDescription; busy = false; return }
        let p = Process(), output = Pipe()
        p.executableURL = URL(fileURLWithPath: py); p.arguments = engineArguments(["job", request.path])
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
                    self.error = "The task ended before a verified result was produced. See Task details for the error."
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
        case "project":
            project = (e["path"] as? String).map { URL(fileURLWithPath: $0) }
        case "progress":
            phase = e["phase"] as? String ?? phase; detail = e["detail"] as? String ?? ""; fraction = e["fraction"] as? Double
        case "warning": warning = e["message"] as? String ?? ""
        case "recovery":
            let good = e["verified"] as? Int ?? 0, total = e["total"] as? Int ?? 0
            recoveryVerified = good; recoveryUncertain = e["uncertain"] as? Int ?? 0
            log += "Verified \(good.formatted()) of \(total.formatted()) sectors.\n"
        case "complete":
            phase = workflow == .video ? "Videos ready" : "Recovery finished"; fraction = 1
            result = (e["path"] as? String).map { URL(fileURLWithPath: $0) }
            let report = e["report"] as? [String: Any] ?? [:]
            let outputs = report["outputs"] as? [[String: Any]] ?? []
            savedVideos = outputs.compactMap { ($0["file"] as? String).map { URL(fileURLWithPath: $0) } }
            if savedVideos.isEmpty, let result { savedVideos = [result] }
            if workflow != .video {
                let copies = report["outputs"] as? [[String: Any]] ?? []
                let originals = report["extracted"] as? [[String: Any]] ?? []
                recoveredVideos = (copies.isEmpty ? originals : copies).compactMap { ($0["file"] as? String).map { URL(fileURLWithPath: $0) } }
                selectedRecoveredVideo = recoveredVideos.first?.path ?? ""
                latestRecoveredVideos = recoveredVideos
                preferences.set(recoveredVideos.map(\.path), forKey: "lastRecoveredVideoPaths")
                previousEnhancementSources = recoveredVideos
                latestRecoveredSelection = recoveredVideos.first
                detail = ""
            } else {
                phase = savedVideos.count == 1 ? "Video saved" : "\(savedVideos.count) videos saved"
                detail = savedVideos.map(\.path).joined(separator: "\n")
            }
        case "cancelled": phase = "Stopped"; detail = e["message"] as? String ?? ""; fraction = nil
        case "error": phase = "Needs attention"; error = e["message"] as? String ?? "The task failed."; fraction = nil
        default: break
        }
        if log.count > 30000 { log = String(log.suffix(30000)) }
    }

    func stop() { if process?.isRunning == true { phase = "Stopping safely"; process?.terminate() } }
    func revealProject() {
        let existing = savedVideos.filter { FileManager.default.fileExists(atPath: $0.path) }
        if !existing.isEmpty { NSWorkspace.shared.activateFileViewerSelecting(existing) }
        else if let project { NSWorkspace.shared.open(project) }
    }
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
    @State private var previewExpanded = false
    @State private var earlierReadsExpanded = false
    private let driveRefresh = Timer.publish(every: 10, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 225)
            Divider()
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        header
                        sourceArea
                        if m.workflow != .video && m.result != nil { recoveryResults }
                        if m.workflow == .video { options }
                        destination
                    }.padding(30).frame(maxWidth: .infinity, alignment: .leading)
                }.disabled(m.busy)
                statusBar
            }.background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(minWidth: 960, minHeight: 740)
        .tint(accent)
        .onReceive(driveRefresh) { _ in
            if m.usesDrive { m.refreshDrives() }
        }
        .onChange(of: m.recoverySource) { _, _ in m.changeRecoverySource() }
        .sheet(isPresented: $m.showHelp) { help }
        .sheet(isPresented: $m.showLog) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Task details").font(.title2.bold())
                ScrollView { Text(m.log.isEmpty ? "No messages yet." : m.log).textSelection(.enabled).font(.system(.body, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading) }
                HStack { Spacer(); Button("Done") { m.showLog = false }.keyboardShortcut(.defaultAction) }
            }.padding(24).frame(width: 700, height: 480)
        }
    }

    var sidebar: some View {
        VStack(alignment: .leading, spacing: 26) {
            VStack(spacing: 6) {
                ForEach(Workflow.allCases, id: \.self) { workflow in
                    if workflow == .video {
                        Divider().padding(.vertical, 15)
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
            Button { m.showHelp = true } label: { Label("Help & setup", systemImage: "questionmark.circle") }.buttonStyle(.plain)
            Text("Version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"))").font(.caption2).foregroundStyle(.secondary)
        }.padding(20).background(mist)
    }

    var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(m.workflow.rawValue).font(.system(size: 30, weight: .semibold, design: .rounded)).foregroundStyle(ink)
            if !m.ready { Label(m.dependencyMessage, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
        }
    }

    var recoveryResults: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Recovery results").font(.headline).foregroundStyle(ink)
            Text(m.recoveredVideos.count == 1 ? "1 video track saved" : "\(m.recoveredVideos.count) video tracks saved").font(.title3.weight(.semibold))
            if !m.recoveredVideos.isEmpty {
                Button("Enhance footage", action: m.reviewRecovered)
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(mist, in: RoundedRectangle(cornerRadius: 10))
    }

    var sourceArea: some View {
        VStack(alignment: .leading, spacing: 14) {
            if m.workflow == .recovery {
                Text("Recovery source").font(.headline).foregroundStyle(ink)
                Picker("Recover from", selection: $m.recoverySource) {
                    ForEach(RecoverySource.allCases, id: \.self) { source in
                        Text(source.rawValue).tag(source)
                    }
                }.pickerStyle(.segmented).frame(maxWidth: 360)
            }
            if m.usesDrive {
                HStack {
                    Label("Inserted VCD / SVCD", systemImage: "opticaldisc").font(.headline)
                    Spacer()
                    Button(m.refreshing ? "Checking…" : "Refresh", action: m.refreshDrives).disabled(m.refreshing)
                }
                if !m.drives.isEmpty {
                    Picker("CD drive", selection: $m.selectedDrive) {
                        ForEach(m.drives.indices, id: \.self) { i in
                            let d = m.drives[i]
                            Text("\(d["name"] as? String ?? "CD") (\(d["device"] as? String ?? ""))").tag(d["device"] as? String ?? "")
                        }
                    }
                }
                if m.drives.isEmpty {
                    Label(m.driveMessage, systemImage: "info.circle")
                        .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                if m.tools["ddrescue"] == nil && m.ready {
                    Text("The built-in CD reading tool is missing. Reinstall the app.").font(.caption).foregroundStyle(.orange)
                }
                DisclosureGroup("Add earlier reads of this disc (optional)", isExpanded: $earlierReadsExpanded) {
                    sourceFiles.padding(.top, 12)
                }
            } else { sourceFiles }
        }
    }

    var sourceFiles: some View {
        VStack(alignment: .leading, spacing: 14) {
            if m.workflow == .video && !m.sources.isEmpty {
                HStack {
                    Text("Videos").font(.headline)
                    Spacer()
                    if !m.latestRecoveredVideos.isEmpty && Set(m.sources) != Set(m.latestRecoveredVideos) {
                        Button("Use recovered videos", action: m.useRecoveredVideos)
                    }
                    Button("Choose videos…", action: m.chooseSource)
                }
                ForEach(Array(m.sources.enumerated()), id: \.element) { index, url in
                    HStack {
                        Text("\(index + 1).").foregroundStyle(.secondary)
                        Button(url.lastPathComponent) { m.player = AVPlayer(url: url); previewExpanded = true }.buttonStyle(.plain).lineLimit(1)
                        Spacer()
                        Button { m.sources.swapAt(index, index - 1) } label: { Image(systemName: "arrow.up") }.disabled(index == 0).help("Move earlier")
                        Button { m.sources.swapAt(index, index + 1) } label: { Image(systemName: "arrow.down") }.disabled(index == m.sources.count - 1).help("Move later")
                        Button { m.sources.remove(at: index); if m.sources.count < 2 { m.combineOutput = false } } label: { Image(systemName: "minus.circle") }.help("Remove video")
                    }
                }
            }
            if m.workflow == .video, let player = m.player, !m.sources.isEmpty {
                DisclosureGroup("Preview", isExpanded: $previewExpanded) {
                    NativeVideoPlayer(player: player).frame(height: 180).background(.black).clipShape(RoundedRectangle(cornerRadius: 9)).padding(.top, 8)
                }

            } else {
                VStack(spacing: 12) {
                    Image(systemName: m.workflow == .video ? "film.stack" : "opticaldisc").font(.system(size: 32, weight: .light)).foregroundStyle(accent)
                    Text(m.workflow == .video ? "Drop videos here" : m.usesDrive ? "Add earlier reads, if you have them" : "Drop images from the same CD here").font(.headline)
                    Text(m.workflow == .video ? "MP4, M4V, MPEG, MOV" : "Raw .bin or .iso")
                        .font(.callout).foregroundStyle(.secondary)
                    Button(m.workflow == .video ? "Choose videos…" : "Choose images…", action: m.chooseSource).controlSize(.large)
                }.frame(maxWidth: .infinity).padding(24)
                    .background(dropActive ? accent.opacity(0.12) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(accent.opacity(dropActive ? 0.8 : 0.22), style: StrokeStyle(lineWidth: 1, dash: [5,4])))
                    .onDrop(of: [UTType.fileURL.identifier], isTargeted: $dropActive) { providers in
                        let workflow = m.workflow
                        let group = DispatchGroup(), lock = NSLock()
                        var urls: [URL] = []
                        for provider in providers {
                            group.enter()
                            _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                                if let data, let url = URL(dataRepresentation: data, relativeTo: nil) {
                                    lock.lock(); urls.append(url); lock.unlock()
                                }
                                group.leave()
                            }
                        }
                        group.notify(queue: .main) {
                            guard m.workflow == workflow else { return }
                            m.add(urls, replaceCatalog: workflow == .video)
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
            }
        }
    }

    var options: some View {
        VStack(alignment: .leading, spacing: 14) {
            Divider()
            Text("Output").font(.headline).foregroundStyle(ink)
            if m.sources.count > 1 {
                Picker("Create", selection: $m.combineOutput) {
                    Text("Separate videos").tag(false)
                    Text("One combined video").tag(true)
                }.pickerStyle(.segmented)
            }
            HStack {
                Text("Name")
                TextField("Video name", text: $m.outputName).textFieldStyle(.roundedBorder)
            }
            if !m.validOutputName { Text("Use a short video name without slashes or colons.").font(.caption).foregroundStyle(.red) }
            exportOptions
            VStack(alignment: .leading, spacing: 3) {
                ForEach(m.outputNames, id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
            }
            if m.outputExists { Text("A file with this name exists. Change the name or folder.").font(.caption).foregroundStyle(.red) }
            if m.preset != "original" { repairOptions }
        }
    }

    var exportOptions: some View {
        VStack(alignment: .leading, spacing: 14) {
            Picker("Format", selection: $m.preset) {
                Text("Original MPEG · no conversion").tag("original")
                Text("Original display size · H.264").tag("native")
                Text("1080p compact copy · H.265").tag("share")
                Text("1080p high-quality copy · H.264").tag("hd")
            }.pickerStyle(.menu)
            if m.preset != "original" { Toggle("Gentle noise reduction and sharpening", isOn: $m.enhance) }
        }
    }

    var repairOptions: some View {
                DisclosureGroup("Repair specific moments (optional)", isExpanded: $repairsExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("One start-end range per line, relative to each output video.").font(.caption).foregroundStyle(.secondary)
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
            HStack { Text("Save videos in").font(.headline); Spacer(); Button("Choose folder…", action: m.chooseDestination) }
            Label(m.destination.path, systemImage: "folder").font(.callout).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
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
                    if !m.detail.isEmpty { Text(m.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2).truncationMode(.middle).textSelection(.enabled).help(m.detail) }
                    if m.busy {
                        if let f = m.fraction { ProgressView(value: f).frame(maxWidth: 340) }
                        else { ProgressView().controlSize(.small) }
                    }
                }
                Spacer()
                if m.busy { Button("Stop", action: m.stop).controlSize(.large) }
                else {
                    if m.result != nil {
                        Button("Show in Finder", action: m.revealProject)
                        if m.workflow == .video { Button("Play", action: m.playResult) }
                    }
                    Button(m.workflow == .video ? (m.combineOutput || m.sources.count == 1 ? "Create video" : "Create videos") : "Start recovery") { m.start() }
                        .buttonStyle(.borderedProminent).controlSize(.large).disabled(!m.canRun)
                }
                Button { m.showLog = true } label: { Image(systemName: "text.alignleft") }.help("Task details")
            }
        }.padding(.horizontal, 30).padding(.bottom, 20).padding(.top, 5)
    }

    var help: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Help & setup").font(.system(size: 25, weight: .semibold, design: .rounded)).foregroundStyle(ink)
            Divider()
            Text("Built-in tools").font(.headline)
            ForEach(["ffmpeg", "ffprobe", "ddrescue"], id: \.self) { name in
                HStack { Image(systemName: m.tools[name] != nil ? "checkmark.circle.fill" : "exclamationmark.circle").foregroundStyle(m.tools[name] != nil ? accent : .orange); Text(name); Spacer(); Text(m.tools[name] ?? "Unavailable").font(.caption).foregroundStyle(.secondary) }
            }
            Button("Open third-party licenses") {
                if let url = Bundle.main.resourceURL?.appendingPathComponent("runtime/licenses") { NSWorkspace.shared.open(url) }
            }
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
            alert.informativeText = "Temporary working files will be removed."
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
