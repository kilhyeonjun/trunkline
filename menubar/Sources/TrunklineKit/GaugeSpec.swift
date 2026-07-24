import Foundation

/// 게이지 채움 색조 — "codex" 문자열 자체가 PurityTests 금지어라 "main"으로 명명.
public enum GaugeTint: Equatable { case main, claude }

/// fill<90 normal / 90..<100 warn / >=100 exhausted.
public enum GaugeSeverity: Equatable { case normal, warn, exhausted }

public struct GaugeSpec: Equatable {
    public let title: String
    public let fillPercent: Double
    public let tint: GaugeTint
    public let severity: GaugeSeverity
    public let dimmed: Bool
    public let expectedPercent: Double?
    public let bucket: PaceBucket?
    public let leftText: String
    public let rightText: String
    public let accessibilityText: String

    public init(title: String, fillPercent: Double, tint: GaugeTint, severity: GaugeSeverity,
                dimmed: Bool, expectedPercent: Double?, bucket: PaceBucket?,
                leftText: String, rightText: String, accessibilityText: String) {
        self.title = title
        self.fillPercent = fillPercent
        self.tint = tint
        self.severity = severity
        self.dimmed = dimmed
        self.expectedPercent = expectedPercent
        self.bucket = bucket
        self.leftText = leftText
        self.rightText = rightText
        self.accessibilityText = accessibilityText
    }
}

public struct StyledRun: Equatable {
    public let text: String
    public let style: RunStyle

    public init(text: String, style: RunStyle) {
        self.text = text
        self.style = style
    }
}

public enum RunStyle: Equatable { case normal, dim, warn, danger }

/// rightRuns를 " · " 한 줄로 병합 + 대표 스타일(danger > warn > normal > dim 우선순위)
/// — 개행 없이 한 줄 표시하기 위함(멀티 tab 세로 적층 버그 회피).
public func joinedRightRunsText(_ runs: [StyledRun]) -> (text: String, style: RunStyle) {
    guard !runs.isEmpty else { return ("", .dim) }
    let text = runs.map(\.text).joined(separator: " · ")
    let priority: [RunStyle] = [.danger, .warn, .normal, .dim]
    let style = priority.first { style in runs.contains { $0.style == style } } ?? .dim
    return (text, style)
}

/// GaugeRowView 하단 좌·우 텍스트 폭 분배 — rightText를 행 폭의 60%로 상한해
/// leftText(남음%·상태, 더 중요한 정보)가 밀리지 않게 남은 폭을 확보.
public func bottomTextLayout(width: CGFloat, rightTextWidth: CGFloat, gap: CGFloat) -> (rightDrawWidth: CGFloat, leftMaxWidth: CGFloat) {
    let rightMaxWidth = width * 0.6
    let rightDrawWidth = min(max(rightTextWidth, 0), rightMaxWidth)
    let leftMaxWidth = max(width - rightDrawWidth - gap, 0)
    return (rightDrawWidth, leftMaxWidth)
}

/// wham 창 길이(분) → 사람용 라벨. cli.py `_window_label`과 동기 — 구간 매핑(300/10080/<60/<2880/else)
/// 변경 시 양쪽 테스트(GaugeSpecTests.swift ↔ tests/test_cli.py) 동시 갱신 필요. 한국어 텍스트는 브리프 정확값.
public func windowTitle(minutes: Int) -> String {
    if minutes == 300 { return "세션 · 5시간 창" }
    if minutes == 10080 { return "주간 · 7일 창" }
    if minutes < 60 { return "세션 · \(minutes)분 창" }
    if minutes < 2880 { return "세션 · \(minutes / 60)시간 창" }
    return "주간 · \(minutes / 1440)일 창"
}

/// codex 계정 plan 원문(identity `chatgpt_plan_type`) → 표시 문자열.
/// 알려진 4종 고정 표기, 그 외는 원문 첫글자만 대문자화(원문 노출 대신 최소 정규화).
public func planDisplayText(_ raw: String) -> String {
    let known = ["pro": "Pro", "plus": "Plus", "free": "Free", "team": "Team"]
    if let mapped = known[raw] { return mapped }
    guard let first = raw.first else { return raw }
    return first.uppercased() + raw.dropFirst()
}

/// claude tier 원문(organizationRateLimitTier) → 표시 문자열.
/// 매핑 불가는 nil — 내부 식별자를 그대로 노출하면 UI 소음이므로 표기 생략.
public func claudeTierDisplayText(_ raw: String?) -> String? {
    guard let raw else { return nil }
    let known = ["default_claude_max_20x": "Max 20x", "default_claude_max_5x": "Max 5x"]
    if let mapped = known[raw] { return mapped }
    if raw.hasSuffix("_pro") { return "Pro" }
    return nil
}

public func severity(forFillPercent fill: Double) -> GaugeSeverity {
    if fill >= 100 { return .exhausted }
    if fill >= 90 { return .warn }
    return .normal
}

/// 메뉴 열림 시 usage 재조회 스로틀 판정 — 마지막 "시도" 60s 이내거나 in-flight면 skip.
public func shouldTriggerMenuReload(now: Double, lastAttempt: Double?, inFlight: Bool) -> Bool {
    if inFlight { return false }
    guard let lastAttempt else { return true }
    return now - lastAttempt >= 60
}

/// GaugeSpec 조립 — computePace 결과를 브리프 정확 문자열로 변환.
public func makeGaugeSpec(
    title: String,
    usedPercent: Double,
    resetsAt: Double?,
    windowMinutes: Int?,
    now: Double,
    wallClock: Double,
    dataAgeSeconds: Double?,
    tint: GaugeTint = .main
) -> GaugeSpec {
    let pace = computePace(usedPercent: usedPercent, resetsAt: resetsAt,
                           windowMinutes: windowMinutes, now: now, wallClock: wallClock,
                           dataAgeSeconds: dataAgeSeconds)

    let leftText: String
    if let stale = pace.staleOverride {
        leftText = stale
    } else if usedPercent >= 100 {
        leftText = "\(remainText(usedPercent: usedPercent)) · 소진됨"
    } else if let statusWord = pace.statusWord {
        leftText = "\(remainText(usedPercent: usedPercent)) · \(statusWord)"
    } else {
        leftText = remainText(usedPercent: usedPercent)
    }

    var rightText = ""
    if pace.staleOverride == nil, let reset = pace.resetText {
        rightText = reset
        if let eta = pace.etaText { rightText += " · \(eta)" }
    }

    return GaugeSpec(
        title: title,
        fillPercent: usedPercent,
        tint: tint,
        severity: severity(forFillPercent: usedPercent),
        dimmed: pace.staleOverride != nil,
        expectedPercent: pace.expectedPercent,
        bucket: pace.bucket,
        leftText: leftText,
        rightText: rightText,
        accessibilityText: "\(title) — \(leftText)" + (rightText.isEmpty ? "" : " · \(rightText)")
    )
}
