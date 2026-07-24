import XCTest
@testable import TrunklineKit

final class MenuReloadThrottleTests: XCTestCase {
    // 마지막 "시도" 60s 이내 → skip.
    func testSkipsWithinSixtySeconds() {
        XCTAssertFalse(shouldTriggerMenuReload(now: 100, lastAttempt: 41, inFlight: false))
    }

    // 정확히 60s 경과 → 허용.
    func testAllowsAtExactlySixtySeconds() {
        XCTAssertTrue(shouldTriggerMenuReload(now: 100, lastAttempt: 40, inFlight: false))
    }

    // 60s 넘게 경과 → 허용.
    func testAllowsAfterSixtySeconds() {
        XCTAssertTrue(shouldTriggerMenuReload(now: 200, lastAttempt: 40, inFlight: false))
    }

    // in-flight면 시간 무관 skip.
    func testSkipsWhenInFlightRegardlessOfElapsed() {
        XCTAssertFalse(shouldTriggerMenuReload(now: 1000, lastAttempt: 0, inFlight: true))
    }

    // 시도 이력 없음(nil) → 허용.
    func testAllowsWhenNoPriorAttempt() {
        XCTAssertTrue(shouldTriggerMenuReload(now: 0, lastAttempt: nil, inFlight: false))
    }
}
