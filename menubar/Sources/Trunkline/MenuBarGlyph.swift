import AppKit

/// 코드 드로잉 메뉴바 글리프 — Assets/icon-menubar.svg 좌표(1024 viewBox, 1pt=64u)를
/// 64로 나눠 16x16 템플릿 이미지로 재현.
enum MenuBarGlyph {
    static func make() -> NSImage {
        let image = NSImage(size: NSSize(width: 16, height: 16), flipped: true) { rect in
            NSColor.black.set()

            // 캡슐 외곽선(게이지 트랙): 13 x 5pt, 1.5pt stroke. 16pt 캔버스 세로 중앙 정렬.
            let outline = NSBezierPath(roundedRect: NSRect(x: 1.5, y: 5.5, width: 13, height: 5),
                                       xRadius: 2.5, yRadius: 2.5)
            outline.lineWidth = 1.5
            outline.stroke()

            // 채움 캡슐 — 틱 앞에서 끊기는 펀치 갭.
            let fill = NSBezierPath(roundedRect: NSRect(x: 2.75, y: 6.75, width: 5.625, height: 2.5),
                                    xRadius: 1.25, yRadius: 1.25)
            fill.fill()

            // pace 틱 — 캡슐 위아래로 1pt 돌출.
            let tick = NSBezierPath(roundedRect: NSRect(x: 9.375, y: 4.5, width: 1.5, height: 7),
                                    xRadius: 0.75, yRadius: 0.75)
            tick.fill()

            return true
        }
        image.isTemplate = true
        return image
    }
}
