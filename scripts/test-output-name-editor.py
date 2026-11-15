#!/usr/bin/env python3
"""Test actual SwiftUI Name editing through the bundled engine using three real MPEGs.

The window remains off-screen. Inputs are read-only; generated videos and isolated
preferences are removed after the test. Requires Xcode command-line tools.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--app', type=Path, default=ROOT/'dist/Reel Rescue.app')
parser.add_argument('sources', type=Path, nargs=3)
args = parser.parse_args()
if any(not source.is_file() for source in args.sources):
    parser.error('Choose three existing MPEG files')
source = (ROOT/'native/ReelRescue.swift').read_text().split('@main struct ReelRescueApp')[0]
harness = r'''
import SwiftUI
import Foundation
import AppKit
@main struct WidgetNameAcceptance {
 @MainActor static func main() throws {
  let app=NSApplication.shared
  app.setActivationPolicy(.prohibited)
  let appURL=URL(fileURLWithPath:CommandLine.arguments[1])
  let engine=appURL.appendingPathComponent("Contents/Resources/runtime/engine/ReelRescueEngine")
  let inputs=CommandLine.arguments[2...4].map { URL(fileURLWithPath:$0) }
  let suite="ReelWidgetNames-"+UUID().uuidString
  let preferences=UserDefaults(suiteName:suite)!
  defer { preferences.removePersistentDomain(forName:suite) }
  let directory=FileManager.default.temporaryDirectory.appendingPathComponent(suite)
  try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
  defer { try? FileManager.default.removeItem(at:directory) }
  let model=Model(preferences:preferences)
  model.python=engine.path
  let bin=appURL.appendingPathComponent("Contents/Resources/runtime/bin")
  model.tools=["ffmpeg":bin.appendingPathComponent("ffmpeg").path,"ffprobe":bin.appendingPathComponent("ffprobe").path]
  model.selectWorkflow(.video)
  model.add(inputs)
  model.destination=directory;model.container="mpeg";model.combineOutput=false
  let host=NSHostingView(rootView:ContentView().environmentObject(model))
  let window=NSWindow(contentRect:NSRect(x:-20000,y:-20000,width:1120,height:850),styleMask:[.titled,.closable],backing:.buffered,defer:false)
  window.contentView=host
  host.layoutSubtreeIfNeeded()
  for _ in 0..<20 { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
  func fields(_ view:NSView)->[NSTextField] { (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap(fields) }
  let candidates=fields(host)
  print("Editable native fields",candidates.filter(\.isEditable).map { ($0.placeholderString ?? "",$0.stringValue) })
  guard let field=candidates.first(where: {$0.isEditable && $0.placeholderString=="Video name"}) else { fatalError("Cannot locate the actual Name text field") }
  precondition(window.makeFirstResponder(field))
  guard let editor=field.currentEditor() as? NSTextView else { fatalError("Name field has no editor") }
  editor.selectAll(nil)
  let entered="Name typed into field – été.v2.mp4"
  editor.insertText(entered,replacementRange:editor.selectedRange())
  print("Entered",entered,"Binding before blur",model.outputName)
  for _ in 0..<2 { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
  print("Binding before Create",model.outputName)
  precondition(model.outputName==entered,"The actual Name field did not update the model before Create")
  model.start()
  let deadline=Date().addingTimeInterval(120)
  while model.busy && Date()<deadline { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
  precondition(!model.busy && model.error.isEmpty,model.error)
  precondition(model.savedVideos.map(\.lastPathComponent)==["Name typed into field – été.v2_01.mpg","Name typed into field – été.v2_02.mpg","Name typed into field – été.v2_03.mpg"])
  print("PASS actual SwiftUI Name editor → Create → frozen engine → three full-length files, while the editor still has focus")
  let combinedFolder=directory.appendingPathComponent("combined")
  try FileManager.default.createDirectory(at:combinedFolder,withIntermediateDirectories:true)
  model.destination=combinedFolder;model.combineOutput=true
  for _ in 0..<4 { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
  guard let combinedField=fields(host).first(where: {$0.isEditable && $0.placeholderString=="Video name"}) else { fatalError("Name field disappeared") }
  precondition(window.makeFirstResponder(combinedField))
  let combinedEditor=combinedField.currentEditor() as! NSTextView
  combinedEditor.selectAll(nil)
  combinedEditor.insertText("Combined custom name – été.v3.mov",replacementRange:combinedEditor.selectedRange())
  precondition(model.outputName=="Combined custom name – été.v3.mov")
  model.start()
  let combinedDeadline=Date().addingTimeInterval(300)
  while model.busy && Date()<combinedDeadline { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
  precondition(!model.busy && model.error.isEmpty,model.error)
  precondition(model.savedVideos.map(\.lastPathComponent)==["Combined custom name – été.v3.mpg"])
  print("PASS actual Name editor → Create combined → full-length renamed combined video")
  window.orderOut(nil)
 }
}

'''
with tempfile.TemporaryDirectory(prefix='ReelNameEditorTest-') as directory:
    root = Path(directory)
    (root/'Model.swift').write_text(source)
    (root/'Names.swift').write_text(harness)
    executable = root/'NameEditorTest'
    subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(ROOT/'build/module-cache'),
        '-parse-as-library',str(root/'Model.swift'),str(root/'Names.swift'),'-o',str(executable)],check=True)
    subprocess.run([str(executable),str(args.app.resolve()),*[str(p.resolve()) for p in args.sources]],check=True)
