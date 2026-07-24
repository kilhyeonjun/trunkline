import XCTest
@testable import TrunklineKit

final class GaugeSpecTests: XCTestCase {
    // MARK: - windowTitle 라벨 매핑 (T2 창 길이 규칙과 동일 매핑, 한국어 텍스트는 브리프 정확값)

    func testWindowTitleSessionFiveHour() {
        XCTAssertEqual(windowTitle(minutes: 300), "세션 · 5시간 창")
    }

    func testWindowTitleWeeklySevenDay() {
        XCTAssertEqual(windowTitle(minutes: 10080), "주간 · 7일 창")
    }

    func testWindowTitleUnderTwoDaysDerivedHours() {
        XCTAssertEqual(windowTitle(minutes: 120), "세션 · 2시간 창")
    }

    func testWindowTitleOverTwoDaysDerivedDays() {
        XCTAssertEqual(windowTitle(minutes: 4320), "주간 · 3일 창")
    }

    // U — 60분 미만 창(비표준 limit_window_seconds)은 "N분 창". cli.py _window_label과 동기 —
    // 케이스 표 변경 시 양쪽(여기 ↔ tests/test_cli.py) 동시 갱신.
    func testWindowTitleUnderOneHourDerivedMinutes() {
        XCTAssertEqual(windowTitle(minutes: 45), "세션 · 45분 창")
    }

    // MARK: - severity (fill<90 normal / 90..<100 warn / >=100 exhausted)

    func testSeverityBoundaries() {
        XCTAssertEqual(severity(forFillPercent: 89.999), .normal)
        XCTAssertEqual(severity(forFillPercent: 90), .warn)
        XCTAssertEqual(severity(forFillPercent: 99.999), .warn)
        XCTAssertEqual(severity(forFillPercent: 100), .exhausted)
        XCTAssertEqual(severity(forFillPercent: 150), .exhausted)
    }

    // MARK: - makeGaugeSpec 조립

    func testGaugeSpecNormalWithPaceMarker() {
        // 7일 창 브리프 예시: used=26%, resetsAt=+105h, expected=37.5 → reserve, "12% 예비"
        let now: Double = 0
        let resetsAt = 105 * 3600.0
        let spec = makeGaugeSpec(title: "주간 · 7일 창 (personal)", usedPercent: 26,
                                  resetsAt: resetsAt, windowMinutes: 7 * 24 * 60,
                                  now: now, wallClock: now, dataAgeSeconds: 0)
        XCTAssertEqual(spec.title, "주간 · 7일 창 (personal)")
        XCTAssertEqual(spec.fillPercent, 26)
        XCTAssertEqual(spec.severity, .normal)
        XCTAssertFalse(spec.dimmed)
        XCTAssertEqual(spec.expectedPercent!, 37.5, accuracy: 0.0001)
        XCTAssertEqual(spec.bucket, .reserve)
        XCTAssertEqual(spec.leftText, "74% 남음 · 12% 여유")
        XCTAssertEqual(spec.rightText, "4일 9시간 후 리셋 · 리셋까지 유지")
    }

    func testGaugeSpecExhaustedSeverityAndLeftText() {
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 100,
                                  resetsAt: 1000, windowMinutes: 300,
                                  now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(spec.severity, .exhausted)
        XCTAssertEqual(spec.tint, .main)
        XCTAssertEqual(spec.leftText, "0% 남음 · 소진됨")
    }

    func testGaugeSpecStaleOverrideResetOnlyDataFreshDimmedAndNilMarker() {
        // resetsAt < wallClock, 데이터는 신선 → 기존 staleOverride, marker/bucket nil, dimmed true
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 52,
                                  resetsAt: 500, windowMinutes: 100 * 60,
                                  now: 400, wallClock: 600, dataAgeSeconds: 0)
        XCTAssertTrue(spec.dimmed)
        XCTAssertNil(spec.expectedPercent)
        XCTAssertNil(spec.bucket)
        XCTAssertEqual(spec.leftText, "리셋 지남 — 갱신 필요")
        XCTAssertEqual(spec.rightText, "")
    }

    func testGaugeSpecStaleOverrideDataAlsoStaleUsesDataAgeText() {
        // resetsAt < wallClock 이고 dataAge > 창길이 → "N전 데이터" 문구, dimmed true
        let duration = 100.0 * 3600
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 52,
                                  resetsAt: 500, windowMinutes: 100 * 60,
                                  now: 400, wallClock: 600, dataAgeSeconds: duration + 3600)
        XCTAssertTrue(spec.dimmed)
        XCTAssertNil(spec.expectedPercent)
        XCTAssertNil(spec.bucket)
        XCTAssertEqual(spec.leftText, "4일 5시간 전 데이터 — 사용 시 자동 갱신")
        XCTAssertEqual(spec.rightText, "")
    }

    func testGaugeSpecNoResetNoWindowRightTextEmpty() {
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 10,
                                  resetsAt: nil, windowMinutes: nil,
                                  now: 0, wallClock: 0, dataAgeSeconds: nil)
        XCTAssertEqual(spec.rightText, "")
        XCTAssertNil(spec.expectedPercent)
        XCTAssertNil(spec.bucket)
        XCTAssertFalse(spec.dimmed)
    }

    func testGaugeSpecClaudeTint() {
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 10, resetsAt: nil,
                                  windowMinutes: nil, now: 0, wallClock: 0, dataAgeSeconds: nil,
                                  tint: .claude)
        XCTAssertEqual(spec.tint, .claude)
    }

    func testGaugeSpecResetTextOnlyNoEta() {
        // windowMinutes nil → pace 게이트 자체가 막혀 etaText 없음, resetText만
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 52,
                                  resetsAt: 32 * 3600, windowMinutes: nil,
                                  now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(spec.rightText, "1일 8시간 후 리셋")
    }

    func testGaugeSpecAccessibilityTextContainsTitleAndLeftText() {
        let spec = makeGaugeSpec(title: "세션 · 5시간 창", usedPercent: 26, resetsAt: nil,
                                  windowMinutes: nil, now: 0, wallClock: 0, dataAgeSeconds: nil)
        XCTAssertTrue(spec.accessibilityText.contains("세션 · 5시간 창"))
        XCTAssertTrue(spec.accessibilityText.contains(spec.leftText))
    }

    // MARK: - joinedRightRunsText (헤더 우측 rightRuns 한 줄 병합 — 개행 방지)

    func testJoinedRightRunsTextJoinsWithMiddleDot() {
        let runs = [StyledRun(text: "방금 업데이트됨", style: .dim),
                    StyledRun(text: "활성: personal", style: .normal),
                    StyledRun(text: "모드: auto", style: .normal)]
        let joined = joinedRightRunsText(runs)
        XCTAssertEqual(joined.text, "방금 업데이트됨 · 활성: personal · 모드: auto")
        XCTAssertEqual(joined.style, .normal)
    }

    func testJoinedRightRunsTextDangerOutranksWarnAndNormal() {
        let runs = [StyledRun(text: "a", style: .normal), StyledRun(text: "b", style: .warn),
                    StyledRun(text: "c", style: .danger), StyledRun(text: "d", style: .dim)]
        XCTAssertEqual(joinedRightRunsText(runs).style, .danger)
    }

    func testJoinedRightRunsTextWarnOutranksNormalAndDim() {
        let runs = [StyledRun(text: "a", style: .dim), StyledRun(text: "b", style: .normal),
                    StyledRun(text: "c", style: .warn)]
        XCTAssertEqual(joinedRightRunsText(runs).style, .warn)
    }

    func testJoinedRightRunsTextSingleRunKeepsItsStyle() {
        XCTAssertEqual(joinedRightRunsText([StyledRun(text: "— 소진", style: .danger)]).style, .danger)
    }

    func testJoinedRightRunsTextEmptyIsEmptyDim() {
        let joined = joinedRightRunsText([])
        XCTAssertEqual(joined.text, "")
        XCTAssertEqual(joined.style, .dim)
    }

    // MARK: - bottomTextLayout (GaugeRowView 하단 좌우 텍스트 겹침 방지 폭 분배)

    func testBottomTextLayoutShortRightTextKeepsFullLeftWidth() {
        // rightText가 짧으면 leftText는 (폭 − rightDrawWidth − gap)까지 그대로 사용
        let layout = bottomTextLayout(width: 280, rightTextWidth: 40, gap: 8)
        XCTAssertEqual(layout.rightDrawWidth, 40, accuracy: 0.0001)
        XCTAssertEqual(layout.leftMaxWidth, 280 - 40 - 8, accuracy: 0.0001)
    }

    func testBottomTextLayoutCapsRightTextAt60PercentOfWidth() {
        // rightText가 폭 대부분을 요구하면 60%로 잘라 좌측 공간을 확보
        let layout = bottomTextLayout(width: 280, rightTextWidth: 260, gap: 8)
        XCTAssertEqual(layout.rightDrawWidth, 280 * 0.6, accuracy: 0.0001)
        XCTAssertEqual(layout.leftMaxWidth, 280 - 280 * 0.6 - 8, accuracy: 0.0001)
    }

    func testBottomTextLayoutNeverNegativeLeftWidth() {
        let layout = bottomTextLayout(width: 20, rightTextWidth: 100, gap: 8)
        XCTAssertGreaterThanOrEqual(layout.leftMaxWidth, 0)
    }
}
