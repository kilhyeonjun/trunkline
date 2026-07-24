import AppKit
import TrunklineKit

/// stateless 게이지 행 — spec을 draw에서만 그린다(상태 없음, 재사용 없음).
final class GaugeRowView: NSView {
    static let rowSize = NSSize(width: 300, height: 58)
    /// 텍스트 행(AppDelegate.attributedTitle)의 우측 정렬 탭이 이 인셋에서 파생 — 두 행 종류의
    /// 우측 정렬선을 일치시키기 위한 공유 상수(완전 일치는 NSMenuItem 텍스트 인셋 특성상 불가, 근사 정렬).
    static let rowInset: CGFloat = 10

    private let spec: GaugeSpec

    init(spec: GaugeSpec) {
        self.spec = spec
        super.init(frame: NSRect(origin: .zero, size: Self.rowSize))
        autoresizingMask = .width
        toolTip = spec.accessibilityText
        setAccessibilityLabel(spec.accessibilityText)
        setAccessibilityElement(true)
        setAccessibilityRole(.staticText)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) not supported") }

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        let scale = window?.backingScaleFactor ?? (NSScreen.main?.backingScaleFactor ?? 2)
        let inset = Self.rowInset
        let barHeight: CGFloat = 6
        let barY: CGFloat = 30
        let barRect = NSRect(x: inset, y: barY, width: bounds.width - inset * 2, height: barHeight)

        drawTitle(in: NSRect(x: inset, y: 4, width: bounds.width - inset * 2, height: 16))
        drawBar(barRect, scale: scale)
        drawBottomText(y: bounds.height - 20, width: bounds.width - inset * 2, x: inset)
    }

    private func drawTitle(in rect: NSRect) {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byTruncatingTail
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.5),
            .foregroundColor: NSColor.secondaryLabelColor,
            .paragraphStyle: paragraph,
        ]
        NSAttributedString(string: spec.title, attributes: attrs).draw(in: rect)
    }

    private func drawBar(_ rect: NSRect, scale: CGFloat) {
        let track = NSBezierPath(roundedRect: rect, xRadius: rect.height / 2, yRadius: rect.height / 2)
        NSColor.tertiaryLabelColor.setFill()
        track.fill()

        let fillWidth = rect.width * CGFloat(min(max(spec.fillPercent, 0), 100) / 100)
        if fillWidth > 0 {
            let fillRect = NSRect(x: rect.minX, y: rect.minY, width: fillWidth, height: rect.height)
            let fillPath = NSBezierPath(roundedRect: fillRect, xRadius: rect.height / 2, yRadius: rect.height / 2)
            let color = fillColor()
            (spec.dimmed ? color.withAlphaComponent(0.45) : color).setFill()
            fillPath.fill()
        }

        drawMarker(barRect: rect, scale: scale)
    }

    private func fillColor() -> NSColor {
        switch spec.severity {
        case .exhausted: return .systemRed
        case .warn: return .systemOrange
        case .normal:
            switch spec.tint {
            case .main: return .systemTeal
            case .claude: return Self.claudeTint
            }
        }
    }

    static let claudeTint = NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(red: 0xD9 / 255, green: 0x77 / 255, blue: 0x57 / 255, alpha: 1)
            : NSColor(red: 0xC1 / 255, green: 0x5F / 255, blue: 0x3C / 255, alpha: 1)
    }

    private func drawMarker(barRect: NSRect, scale: CGFloat) {
        guard let expected = spec.expectedPercent else { return }
        let rawX = barRect.minX + barRect.width * CGFloat(min(max(expected, 0), 100) / 100)
        let pixelAlignedX = (rawX * scale).rounded() / scale
        let x = min(max(pixelAlignedX, 4), bounds.width - 4)

        let bandWidth: CGFloat = 7
        let bandRect = NSRect(x: x - bandWidth / 2, y: barRect.minY - 2,
                              width: bandWidth, height: barRect.height + 4)

        guard let bucket = spec.bucket else { return }
        let stripeColor: NSColor
        switch bucket {
        case .reserve: stripeColor = .systemGreen
        case .onTrack: stripeColor = .secondaryLabelColor
        case .over: stripeColor = .systemRed
        }

        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: bandRect).setClip()
        NSColor.black.set()
        bandRect.fill(using: .destinationOut)
        NSGraphicsContext.restoreGraphicsState()

        let stripeWidth: CGFloat = 2.5
        let stripeRect = NSRect(x: x - stripeWidth / 2, y: bandRect.minY,
                                width: stripeWidth, height: bandRect.height)
        stripeColor.setFill()
        stripeRect.fill()
    }

    /// 좌(leftText, 남음%·상태 — 더 중요) · 우(rightText, 리셋·소진 ETA) 겹침 방지:
    /// rightText를 먼저 측정해 우측 정렬로 그리고(폭은 행의 60%로 상한),
    /// leftText는 남은 폭(rightText 시작 x − gap)만큼만 byTruncatingTail로 클리핑.
    private func drawBottomText(y: CGFloat, width: CGFloat, x: CGFloat) {
        let font = NSFont.systemFont(ofSize: 11.5)
        let leftColor: NSColor
        switch spec.severity {
        case .exhausted: leftColor = .systemRed
        case .warn: leftColor = .systemOrange
        case .normal: leftColor = .labelColor
        }
        let gap: CGFloat = 8
        let rightAttrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.secondaryLabelColor]
        let rightTextWidth = (spec.rightText as NSString).size(withAttributes: rightAttrs).width
        let layout = bottomTextLayout(width: width, rightTextWidth: rightTextWidth, gap: gap)

        let leftParagraph = NSMutableParagraphStyle()
        leftParagraph.lineBreakMode = .byTruncatingTail
        NSAttributedString(string: spec.leftText, attributes: [
            .font: font, .foregroundColor: leftColor, .paragraphStyle: leftParagraph,
        ]).draw(in: NSRect(x: x, y: y, width: layout.leftMaxWidth, height: 16))

        let rightParagraph = NSMutableParagraphStyle()
        rightParagraph.alignment = .right
        rightParagraph.lineBreakMode = .byTruncatingTail
        NSAttributedString(string: spec.rightText, attributes: [
            .font: font, .foregroundColor: NSColor.secondaryLabelColor, .paragraphStyle: rightParagraph,
        ]).draw(in: NSRect(x: x + width - layout.rightDrawWidth, y: y, width: layout.rightDrawWidth, height: 16))
    }
}
