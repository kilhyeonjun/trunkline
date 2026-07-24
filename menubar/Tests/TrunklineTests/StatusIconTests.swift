import XCTest
@testable import TrunklineKit

final class StatusIconTests: XCTestCase {
    func title(_ json: String, now: Double, grace: Double = 0) -> String {
        statusTitle(state: TrunklineState.load(from: Data(json.utf8)), now: now, wakeGraceUntil: grace)
    }

    // 정상: "P 88%" (J — 잔여율 의미, 100-used_percent) — used_percent 12.5 → 100-12.5=87.5 → Int(rounded())=88
    func testNormalShowsUsedPercent() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true},
                       {"label": "company", "snapshot_ok": false}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": {"type": "fallback", "from": "personal", "to": "company",
                         "at": 100.0, "reason": "personal exhausted"}}}}
        """
        XCTAssertEqual(title(json, now: 1000), "P 88%")
    }

    // observed 없음: "P" (em dash 없이 이니셜만)
    func testMissingObservedShowsDash() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true},
                       {"label": "company", "snapshot_ok": false}],
          "observed": null,
          "last_event": null}}}
        """
        XCTAssertEqual(title(json, now: 1000), "P")
    }

    // 데몬 정지: "⚠︎" (now - updatedAt > 15, wake grace 없음)
    func testStoppedDaemonShowsWarning() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true},
                       {"label": "company", "snapshot_ok": false}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": null}}}
        """
        XCTAssertEqual(title(json, now: 1016), "⚠︎")
    }

    // 스토어 비정상: "⚠︎!" (accounts: [])
    func testBrokenStoreShowsWarningBang() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": null}}}
        """
        XCTAssertEqual(title(json, now: 1000), "⚠︎!")
    }

    // 최근 10분(600s) 내 fallback: "⇄C 88%" (J — 잔여율)
    func testRecentFallbackShowsPrefix() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "company", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true},
                       {"label": "company", "snapshot_ok": true}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": {"type": "fallback", "from": "personal", "to": "company",
                         "at": 900.0, "reason": "personal exhausted"}}}}
        """
        XCTAssertEqual(title(json, now: 1000), "⇄C 88%")
    }

    // state nil: "⚠︎?"
    func testNilStateShowsUnknown() {
        XCTAssertEqual(title("not json", now: 1000), "⚠︎?")
    }

    // T — 상태 버튼 VoiceOver 레이블: 이니셜·%·⚠︎ 축약 대신 풀어 쓴 문장.
    func testAccessibilityLabelRunningStateSpellsOutActiveAndRemainPercent() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": {"used_percent": 42.0, "resets_at": 2000.0, "at": 990.0},
          "last_event": null}}}
        """
        let label = statusAccessibilityLabel(
            state: TrunklineState.load(from: Data(json.utf8)), now: 1000, wakeGraceUntil: 0)
        XCTAssertEqual(label, "Trunkline — 활성 personal, 잔여 58%")
    }

    func testAccessibilityLabelStoppedDaemon() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": null, "last_event": null}}}
        """
        let label = statusAccessibilityLabel(
            state: TrunklineState.load(from: Data(json.utf8)), now: 1016, wakeGraceUntil: 0)
        XCTAssertEqual(label, "Trunkline — 데몬 정지")
    }

    // claude loginWarning 있음 → 타이틀이 "·C⚠︎"로 끝남; 없으면 미포함
    func testClaudeWarnSuffix() {
        let withWarning = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": null},
          "claude": {"login_ok": true, "login_warning": "만료 임박 D-3", "usage": null}}}
        """
        XCTAssertTrue(title(withWarning, now: 1000).hasSuffix("·C⚠︎"))

        let withoutWarning = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": null}}}
        """
        XCTAssertFalse(title(withoutWarning, now: 1000).contains("·C⚠︎"))
    }
}
