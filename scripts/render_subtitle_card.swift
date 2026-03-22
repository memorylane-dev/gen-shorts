#!/usr/bin/env swift

import AppKit
import Foundation

struct Options {
    var textFile = ""
    var output = ""
    var fontFile = ""
    var maxWidth: CGFloat = 900
    var fontName = "BM JUA OTF"
    var fontSize: CGFloat = 54
    var lineSpacing: CGFloat = 6
    var paddingX: CGFloat = 28
    var paddingY: CGFloat = 18
    var boxColor = "black@0.55"
    var textColor = "white"
    var cornerRadius: CGFloat = 22
    var align = "center"
}

func parseArgs() -> Options {
    var options = Options()
    let args = Array(CommandLine.arguments.dropFirst())
    var idx = 0
    while idx < args.count {
        let key = args[idx]
        let value = idx + 1 < args.count ? args[idx + 1] : ""
        switch key {
        case "--text-file":
            options.textFile = value
            idx += 2
        case "--output":
            options.output = value
            idx += 2
        case "--font-file":
            options.fontFile = value
            idx += 2
        case "--max-width":
            options.maxWidth = CGFloat(Double(value) ?? Double(options.maxWidth))
            idx += 2
        case "--font-name":
            options.fontName = value
            idx += 2
        case "--font-size":
            options.fontSize = CGFloat(Double(value) ?? Double(options.fontSize))
            idx += 2
        case "--line-spacing":
            options.lineSpacing = CGFloat(Double(value) ?? Double(options.lineSpacing))
            idx += 2
        case "--padding-x":
            options.paddingX = CGFloat(Double(value) ?? Double(options.paddingX))
            idx += 2
        case "--padding-y":
            options.paddingY = CGFloat(Double(value) ?? Double(options.paddingY))
            idx += 2
        case "--box-color":
            options.boxColor = value
            idx += 2
        case "--text-color":
            options.textColor = value
            idx += 2
        case "--corner-radius":
            options.cornerRadius = CGFloat(Double(value) ?? Double(options.cornerRadius))
            idx += 2
        case "--align":
            options.align = value.lowercased()
            idx += 2
        default:
            idx += 1
        }
    }
    return options
}

func parseColor(_ raw: String, defaultColor: NSColor) -> NSColor {
    let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    if trimmed.isEmpty {
        return defaultColor
    }

    let parts = trimmed.split(separator: "@", maxSplits: 1, omittingEmptySubsequences: false)
    let base = String(parts[0]).lowercased()
    let alpha = parts.count > 1 ? CGFloat(Double(parts[1]) ?? 1.0) : CGFloat(1.0)

    switch base {
    case "white":
        return NSColor.white.withAlphaComponent(alpha)
    case "black":
        return NSColor.black.withAlphaComponent(alpha)
    case "clear", "transparent":
        return NSColor.clear
    default:
        var hex = base
        if hex.hasPrefix("0x") {
            hex.removeFirst(2)
        } else if hex.hasPrefix("#") {
            hex.removeFirst()
        }
        guard hex.count == 6, let value = Int(hex, radix: 16) else {
            return defaultColor.withAlphaComponent(alpha)
        }
        let red = CGFloat((value >> 16) & 0xFF) / 255.0
        let green = CGFloat((value >> 8) & 0xFF) / 255.0
        let blue = CGFloat(value & 0xFF) / 255.0
        return NSColor(red: red, green: green, blue: blue, alpha: alpha)
    }
}

func loadText(_ path: String) throws -> String {
    return try String(contentsOfFile: path, encoding: .utf8).trimmingCharacters(in: .newlines)
}

func registerFontIfNeeded(_ fontFile: String) {
    guard !fontFile.isEmpty else {
        return
    }
    let url = URL(fileURLWithPath: fontFile)
    var error: Unmanaged<CFError>?
    _ = CTFontManagerRegisterFontsForURL(url as CFURL, .process, &error)
}

func fontNamesFromFile(_ fontFile: String) -> [String] {
    guard !fontFile.isEmpty else {
        return []
    }
    let url = URL(fileURLWithPath: fontFile)
    guard let descriptors = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [[CFString: Any]] else {
        return []
    }

    var names: [String] = []
    for descriptor in descriptors {
        for key in [kCTFontNameAttribute, kCTFontFamilyNameAttribute, kCTFontDisplayNameAttribute] {
            if let value = descriptor[key] as? String, !value.isEmpty {
                names.append(value)
            }
        }
    }
    return Array(NSOrderedSet(array: names)) as? [String] ?? names
}

func pickFont(_ fontName: String, _ fontSize: CGFloat, _ fontFile: String) -> NSFont {
    registerFontIfNeeded(fontFile)

    var candidates: [String] = []
    if !fontName.isEmpty {
        candidates.append(fontName)
        candidates.append(fontName.replacingOccurrences(of: "_", with: " "))
        candidates.append(fontName.replacingOccurrences(of: " ", with: "_"))
    }
    candidates.append(contentsOf: fontNamesFromFile(fontFile))
    candidates.append(contentsOf: [
        "BM JUA OTF",
        "BM JUA_OTF",
        "BMJUAOTF",
        "BM Jua",
        "Hiragino Maru Gothic ProN",
    ])
    let ordered = Array(NSOrderedSet(array: candidates.compactMap { $0.isEmpty ? nil : $0 })) as? [String] ?? candidates

    for candidate in ordered {
        if let font = NSFont(name: candidate, size: fontSize) {
            return font
        }
    }
    fputs("warn: font '\(fontName)'을 찾지 못해 시스템 폰트로 대체합니다.\n", stderr)
    return NSFont.systemFont(ofSize: fontSize, weight: .regular)
}

func paragraphStyle(_ align: String, _ lineSpacing: CGFloat) -> NSMutableParagraphStyle {
    let style = NSMutableParagraphStyle()
    switch align {
    case "left":
        style.alignment = .left
    case "right":
        style.alignment = .right
    default:
        style.alignment = .center
    }
    style.lineBreakMode = .byWordWrapping
    style.lineSpacing = lineSpacing
    return style
}

let options = parseArgs()
guard !options.textFile.isEmpty, !options.output.isEmpty else {
    fputs("usage: render_subtitle_card.swift --text-file TEXT --output PNG [options]\n", stderr)
    exit(2)
}

do {
    let text = try loadText(options.textFile)
    let font = pickFont(options.fontName, options.fontSize, options.fontFile)
    let style = paragraphStyle(options.align, options.lineSpacing)
    let attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: parseColor(options.textColor, defaultColor: .white),
        .paragraphStyle: style,
    ]
    let attributed = NSAttributedString(string: text, attributes: attrs)
    let drawingRect = attributed.boundingRect(
        with: NSSize(width: options.maxWidth - options.paddingX * 2, height: 4000),
        options: [.usesLineFragmentOrigin, .usesFontLeading]
    )
    let imageSize = NSSize(
        width: ceil(drawingRect.width) + options.paddingX * 2,
        height: ceil(drawingRect.height) + options.paddingY * 2
    )

    let image = NSImage(size: imageSize)
    image.lockFocus()
    NSColor.clear.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: imageSize)).fill()

    let boxRect = NSRect(origin: .zero, size: imageSize)
    let boxPath = NSBezierPath(roundedRect: boxRect, xRadius: options.cornerRadius, yRadius: options.cornerRadius)
    parseColor(options.boxColor, defaultColor: NSColor.black.withAlphaComponent(0.55)).setFill()
    boxPath.fill()

    attributed.draw(
        with: NSRect(
            x: options.paddingX,
            y: options.paddingY,
            width: imageSize.width - options.paddingX * 2,
            height: imageSize.height - options.paddingY * 2
        ),
        options: [.usesLineFragmentOrigin, .usesFontLeading]
    )
    image.unlockFocus()

    guard
        let tiff = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiff),
        let png = bitmap.representation(using: .png, properties: [:])
    else {
        throw NSError(domain: "render_subtitle_card", code: 1, userInfo: [NSLocalizedDescriptionKey: "PNG 변환에 실패했습니다."])
    }

    try png.write(to: URL(fileURLWithPath: options.output))
} catch {
    fputs("error: \(error.localizedDescription)\n", stderr)
    exit(1)
}
