#!/usr/bin/env python3
"""Exercise the actual Swift model's recovered-footage navigation behavior."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/"native/ReelRescue.swift").read_text().split("@main struct ReelRescueApp")[0]
harness = r'''import Foundation
import AppKit
@main struct NavigationTests {
    @MainActor static func main() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let first = root.appendingPathComponent("Track_01.mp4")
        let second = root.appendingPathComponent("Track_02.mp4")
        let third = root.appendingPathComponent("Track_03.mpg")
        for url in [first,second,third] { try Data().write(to: url) }
        func finish(_ model: Model, _ urls: [URL], originalsOnly: Bool = false) throws {
            let report: [String: Any] = [originalsOnly ? "extracted" : "outputs": urls.map { ["file": $0.path] }]
            model.receive(try JSONSerialization.data(withJSONObject: ["type":"complete", "path":urls[0].path,"report":report]))
        }
        let model = Model()
        try finish(model,[first,second])
        model.selectedRecoveredVideo = second.path
        model.selectWorkflow(.video)
        precondition(model.sources == [second], "Enhancement must default to the selected recovered track")
        precondition(model.latestRecoveredVideos == [first,second], "Track list must survive navigation")
        model.audioRanges = "1-2"
        model.selectWorkflow(.video)
        precondition(model.audioRanges == "1-2", "Clicking the active menu must preserve edits")
        model.selectRecoveredTrack(first.path)
        precondition(model.sources == [first])
        model.selectWorkflow(.recovery)
        model.selectWorkflow(.video)
        precondition(model.sources == [first], "Recovered track choice must survive leaving the page")
        model.selectWorkflow(.recovery)
        try finish(model,[third],originalsOnly:true)
        model.selectWorkflow(.video)
        precondition(model.sources == [third], "A newer extraction must replace the old default, even without viewing copies")
        let manual = Model()
        manual.selectWorkflow(.video)
        manual.add([second])
        manual.selectWorkflow(.recovery)
        manual.selectWorkflow(.video)
        precondition(manual.sources == [second], "Retain manual footage when no recovery has completed")
        manual.add([second,first], replaceCatalog: true)
        precondition(manual.latestRecoveredVideos == [first,second], "Existing MPEG tracks must be selectable as a naturally ordered group")
        precondition(manual.sources == [first])
        print("Recovered-footage navigation checks passed.")
    }
}
'''
with tempfile.TemporaryDirectory(prefix="reel-navigation-") as temp:
    p=Path(temp);(p/"Model.swift").write_text(source);(p/"Tests.swift").write_text(harness)
    subprocess.run(["xcrun","swiftc","-swift-version","5","-module-cache-path",str(ROOT/"build/module-cache"),
        "-parse-as-library",str(p/"Model.swift"),str(p/"Tests.swift"),"-o",str(p/"Tests")],check=True)
    subprocess.run([str(p/"Tests")],check=True)
