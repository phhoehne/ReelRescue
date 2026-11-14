import AppKit
let folder = CommandLine.arguments[1]
try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
for (size, suffix) in [(16,"16x16"),(32,"16x16@2x"),(32,"32x32"),(64,"32x32@2x"),(128,"128x128"),(256,"128x128@2x"),(256,"256x256"),(512,"256x256@2x"),(512,"512x512"),(1024,"512x512@2x")] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.scaleBy(x: CGFloat(size)/1024, y: CGFloat(size)/1024)
    NSColor(red: 0.02, green: 0.35, blue: 0.40, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 70,y: 70,width: 884,height: 884), xRadius: 196,yRadius: 196).fill()
    NSColor(red: 0.93,green: 0.97,blue: 0.96,alpha: 1).setFill()
    NSBezierPath(ovalIn: NSRect(x: 220,y: 220,width: 584,height: 584)).fill()
    NSColor(red: 0.02,green: 0.35,blue: 0.40,alpha: 1).setFill()
    NSBezierPath(ovalIn: NSRect(x: 459,y: 459,width: 106,height: 106)).fill()
    NSColor(red: 0.02,green: 0.35,blue: 0.40,alpha: 1).setStroke()
    let ring = NSBezierPath(ovalIn: NSRect(x: 420,y: 420,width: 184,height: 184))
    ring.lineWidth = 12; ring.stroke()
    for (a,b) in [(NSPoint(x: 583,y: 583),NSPoint(x: 710,y: 710)),
                  (NSPoint(x: 615,y: 556),NSPoint(x: 769,y: 626)),
                  (NSPoint(x: 440,y: 440),NSPoint(x: 314,y: 314))] {
        let scratch = NSBezierPath(); scratch.move(to: a); scratch.line(to: b)
        scratch.lineWidth = 16; scratch.stroke()
    }
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: folder).appendingPathComponent("icon_\(suffix).png"))
}
