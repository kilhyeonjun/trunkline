import XCTest
@testable import TrunklineKit

final class PaceTests: XCTestCase {
    // 7일 창 예시(브리프 §1): used=26%, resetsAt = now + 105h → expected 37.5, delta -11.5
    func testOriginalFormulaWorkedExample() {
        let now: Double = 0
        let resetsAt = 105 * 3600.0
        let r = computePace(usedPercent: 26, resetsAt: resetsAt, windowMinutes: 7 * 24 * 60,
                             now: now, wallClock: now, dataAgeSeconds: 0)
        XCTAssertEqual(r.expectedPercent!, 37.5, accuracy: 0.0001)
        XCTAssertEqual(r.bucket, .reserve)
        XCTAssertEqual(r.statusWord, "12% 여유")   // round(11.5) == 12
    }

    // MARK: - bucket 분류 (Δ<-2 / |Δ|<=2 / Δ>+2)

    func testBucketOnTrackAtBoundary() {
        // duration=100h, elapsed=50h → expected=50; used=52 → delta=2 (경계, onTrack)
        let r = computePace(usedPercent: 52, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.bucket, .onTrack)
        XCTAssertEqual(r.statusWord, "정상 속도")
    }

    func testBucketOverAbovePlusTwo() {
        let r = computePace(usedPercent: 55, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.bucket, .over)
        XCTAssertEqual(r.statusWord, "5% 초과")
    }

    func testBucketReserveBelowMinusTwo() {
        let r = computePace(usedPercent: 45, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.bucket, .reserve)
        XCTAssertEqual(r.statusWord, "5% 여유")
    }

    // MARK: - 게이트 경계 (expected>=3.0 AND remaining>0 AND dataAge<=window AND resetsAt>=wallClock)

    func testGateExpectedExactlyThreePasses() {
        // duration=100h, expected=3 → elapsed=3h
        let r = computePace(usedPercent: 3, resetsAt: 97 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNotNil(r.expectedPercent)
    }

    func testGateExpectedJustBelowThreeFails() {
        // elapsed=2.9h → expected=2.9 < 3.0
        let r = computePace(usedPercent: 3, resetsAt: 97.1 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
        XCTAssertNil(r.bucket)
        XCTAssertNil(r.statusWord)
        XCTAssertNil(r.etaText)
    }

    func testGateRemainingZeroBlocksAtUsed100() {
        let r = computePace(usedPercent: 100, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
    }

    func testGateDataAgeExactlyWindowLengthPasses() {
        // dataAge == duration(=100h in seconds) 통과 (<=)
        let duration = 100.0 * 3600
        let r = computePace(usedPercent: 52, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: duration)
        XCTAssertNotNil(r.expectedPercent)
    }

    func testGateDataAgeOverWindowLengthFails() {
        let duration = 100.0 * 3600
        let r = computePace(usedPercent: 52, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: duration + 1)
        XCTAssertNil(r.expectedPercent)
    }

    func testGateResetsAtBeforeWallClockFails() {
        // resetsAt(절대) < wallClock(절대) → staleOverride 경로, expectedPercent nil
        let r = computePace(usedPercent: 52, resetsAt: 1000, windowMinutes: 100 * 60,
                             now: 900, wallClock: 1001, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
        XCTAssertEqual(r.staleOverride, "리셋 지남 — 갱신 필요")
    }

    func testGateResetsAtEqualsWallClockPasses() {
        let r = computePace(usedPercent: 52, resetsAt: 1000, windowMinutes: 100 * 60,
                             now: 950, wallClock: 1000, dataAgeSeconds: 0)
        XCTAssertNotNil(r.expectedPercent)
        XCTAssertNil(r.staleOverride)
    }

    // MARK: - 원본 가드 5종 (resetsAt nil / windowMinutes nil,<=0 / timeUntilReset<=0 / >duration / elapsed==0&&used>0)

    func testGuardResetsAtNil() {
        let r = computePace(usedPercent: 10, resetsAt: nil, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
    }

    func testGuardWindowMinutesNil() {
        let r = computePace(usedPercent: 10, resetsAt: 50 * 3600, windowMinutes: nil,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
    }

    func testGuardWindowMinutesZeroOrNegative() {
        let r1 = computePace(usedPercent: 10, resetsAt: 50 * 3600, windowMinutes: 0,
                              now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r1.expectedPercent)
        let r2 = computePace(usedPercent: 10, resetsAt: 50 * 3600, windowMinutes: -5,
                              now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r2.expectedPercent)
    }

    func testGuardTimeUntilResetNonPositive() {
        // resetsAt <= now → timeUntilReset <= 0
        let r = computePace(usedPercent: 10, resetsAt: 0, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
    }

    func testGuardTimeUntilResetExceedsDuration() {
        // duration=100h, timeUntilReset=150h > duration
        let r = computePace(usedPercent: 10, resetsAt: 150 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
    }

    func testGuardElapsedZeroWithPositiveUsed() {
        // timeUntilReset == duration → elapsed == 0; used > 0
        let r = computePace(usedPercent: 5, resetsAt: 100 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.expectedPercent)
    }

    // MARK: - staleOverride

    // 리셋만 지남, 데이터는 신선(dataAge <= 창길이) → 기존 문구.
    func testStaleOverrideTextResetOnlyDataFresh() {
        let r = computePace(usedPercent: 52, resetsAt: 500, windowMinutes: 100 * 60,
                             now: 400, wallClock: 600, dataAgeSeconds: 0)
        XCTAssertEqual(r.staleOverride, "리셋 지남 — 갱신 필요")
        XCTAssertNil(r.expectedPercent)
        XCTAssertNil(r.etaText)
        XCTAssertNil(r.resetText)
    }

    // 리셋도 지나고 데이터도 낡음(dataAge > 창길이) → "N전 데이터" 문구.
    func testStaleOverrideTextDataAlsoStale() {
        let duration = 100.0 * 3600
        let r = computePace(usedPercent: 52, resetsAt: 500, windowMinutes: 100 * 60,
                             now: 400, wallClock: 600, dataAgeSeconds: duration + 3600)
        XCTAssertEqual(r.staleOverride, "4일 5시간 전 데이터 — 사용 시 자동 갱신")
        XCTAssertNil(r.expectedPercent)
        XCTAssertNil(r.etaText)
        XCTAssertNil(r.resetText)
    }

    // dataAge == 창길이(경계) → 신선 취급, 기존 문구 유지.
    func testStaleOverrideTextDataAgeExactlyWindowLengthIsFresh() {
        let duration = 100.0 * 3600
        let r = computePace(usedPercent: 52, resetsAt: 500, windowMinutes: 100 * 60,
                             now: 400, wallClock: 600, dataAgeSeconds: duration)
        XCTAssertEqual(r.staleOverride, "리셋 지남 — 갱신 필요")
    }

    // windowMinutes nil → 창길이 비교 불가, 기존 문구로 폴백.
    func testStaleOverrideTextNoWindowFallsBackToResetOnly() {
        let r = computePace(usedPercent: 52, resetsAt: 500, windowMinutes: nil,
                             now: 400, wallClock: 600, dataAgeSeconds: 999_999)
        XCTAssertEqual(r.staleOverride, "리셋 지남 — 갱신 필요")
    }

    func testNoStaleOverrideWhenReadingHealthy() {
        let r = computePace(usedPercent: 52, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertNil(r.staleOverride)
    }

    // MARK: - ETA / willLastToReset

    func testEtaWillLastToReset() {
        // duration=100h, elapsed=50h, used=40 → rate=0.8%/h, remaining=60 → eta=75h < timeUntilReset(50h)?
        // 75 > 50 → willLastToReset true, etaText "리셋까지 유지"
        let r = computePace(usedPercent: 40, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.etaText, "리셋까지 유지")
    }

    func testEtaExhaustionBeforeReset() {
        // duration=100h, elapsed=50h, used=90 → rate=1.8%/h, remaining=10 → eta=10/1.8=5.555h < 50h(timeUntilReset)
        // eta ~= 5h33m → "5시간 33분 후 소진"
        let r = computePace(usedPercent: 90, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.etaText, "5시간 33분 후 소진")
    }

    // MARK: - resetText (relativeText 경유, 상위 2단위·0단위 생략)

    func testResetTextDaysAndHours() {
        let r = computePace(usedPercent: 52, resetsAt: 32 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.resetText, "1일 8시간 후 리셋")
    }

    func testResetTextHoursAndMinutesNoDays() {
        let r = computePace(usedPercent: 52, resetsAt: (2 * 3600 + 20 * 60), windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.resetText, "2시간 20분 후 리셋")
    }

    // MARK: - remainText / relativeText 단위 헬퍼

    func testRemainText() {
        XCTAssertEqual(remainText(usedPercent: 42), "58% 남음")
        XCTAssertEqual(remainText(usedPercent: 0), "100% 남음")
        XCTAssertEqual(remainText(usedPercent: 100), "0% 남음")
    }

    // C — usedPercent가 100 초과(관측 초과 사용) 시 잔여율 하한 0 클램프, 음수 미노출.
    func testRemainTextClampsAtZeroWhenOverHundred() {
        XCTAssertEqual(remainText(usedPercent: 105), "0% 남음")
    }

    func testRelativeTextDaysAndHoursDropsZeroUnit() {
        XCTAssertEqual(relativeText(seconds: 24 * 3600), "1일")            // 0시간 생략
        XCTAssertEqual(relativeText(seconds: 32 * 3600), "1일 8시간")
    }

    func testRelativeTextHoursAndMinutes() {
        XCTAssertEqual(relativeText(seconds: 2 * 3600 + 20 * 60), "2시간 20분")
        XCTAssertEqual(relativeText(seconds: 3600), "1시간")               // 0분 생략
    }

    // B — 1분 미만은 "잠시"(호출부가 " 후 리셋"/" 후 소진"을 붙여 "잠시 후 리셋"/"잠시 후 소진"으로 합성 —
    // 과거 "잠시 후" 반환값은 "잠시 후 후 리셋" 문법 파손을 유발했음).
    func testRelativeTextUnderOneMinuteIsJamsi() {
        XCTAssertEqual(relativeText(seconds: 30), "잠시")
        XCTAssertEqual(relativeText(seconds: 0), "잠시")
    }

    // 리셋/소진 1분 전 합성 결과가 실제로 "잠시 후 리셋"/"잠시 후 소진"이 되는지 호출부 경유로 확인 —
    // 회귀 시 "잠시 후 후 리셋" 같은 조사 중복 파손이 재발함.
    func testResetTextUnderOneMinuteComposesJamsiHuReset() {
        let r = computePace(usedPercent: 52, resetsAt: 30, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.resetText, "잠시 후 리셋")
    }

    func testEtaTextUnderOneMinuteComposesJamsiHuExhaustion() {
        // duration=100h, elapsed=50h, used=99.99 → remaining≈0.01, rate≈2%/h → eta≈18s(<60s)
        let r = computePace(usedPercent: 99.99, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                             now: 0, wallClock: 0, dataAgeSeconds: 0)
        XCTAssertEqual(r.etaText, "잠시 후 소진")
    }

    // MARK: - 한국어 정확값 스팟체크(상태어 전부)

    func testStatusWordExactStrings() {
        XCTAssertEqual(
            computePace(usedPercent: 45, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                        now: 0, wallClock: 0, dataAgeSeconds: 0).statusWord, "5% 여유")
        XCTAssertEqual(
            computePace(usedPercent: 50, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                        now: 0, wallClock: 0, dataAgeSeconds: 0).statusWord, "정상 속도")
        XCTAssertEqual(
            computePace(usedPercent: 55, resetsAt: 50 * 3600, windowMinutes: 100 * 60,
                        now: 0, wallClock: 0, dataAgeSeconds: 0).statusWord, "5% 초과")
    }
}
