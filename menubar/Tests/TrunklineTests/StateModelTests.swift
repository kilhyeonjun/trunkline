import XCTest
@testable import TrunklineKit

final class StateModelTests: XCTestCase {
    let good = """
    {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
      "active": "personal", "mode": "auto",
      "accounts": [{"label": "personal", "snapshot_ok": true},
                   {"label": "company", "snapshot_ok": false}],
      "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
      "last_event": {"type": "fallback", "from": "personal", "to": "company",
                     "at": 900.0, "reason": "personal exhausted"}}}}
    """.data(using: .utf8)!

    let broken = """
    {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
      "active": "personal", "mode": "auto",
      "accounts": [],
      "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
      "last_event": {"type": "fallback", "from": "personal", "to": "company",
                     "at": 900.0, "reason": "personal exhausted"}}}}
    """.data(using: .utf8)!

    func testParsesV2() throws {
        let s = try XCTUnwrap(TrunklineState.load(from: good))
        XCTAssertEqual(s.codex.active, "personal")
        XCTAssertEqual(s.codex.accounts.map(\.label), ["personal", "company"])
        XCTAssertEqual(s.codex.observed?.usedPercent, 12.5)
        XCTAssertEqual(s.codex.lastEvent?.reason, "personal exhausted")
    }

    func testRejectsWrongVersionAndGarbage() {
        XCTAssertNil(TrunklineState.load(from: Data("{\"version\":1}".utf8)))
        XCTAssertNil(TrunklineState.load(from: Data("not json".utf8)))
    }

    func testHealth() throws {
        let s = try XCTUnwrap(TrunklineState.load(from: good))
        XCTAssertEqual(s.health(now: 1010, wakeGraceUntil: 0), .running)
        XCTAssertEqual(s.health(now: 1016, wakeGraceUntil: 0), .stopped)      // 15s 초과
        XCTAssertEqual(s.health(now: 1016, wakeGraceUntil: 1020), .running)   // wake 유예

        let b = try XCTUnwrap(TrunklineState.load(from: broken))
        XCTAssertEqual(b.health(now: 1010, wakeGraceUntil: 0), .storeBroken)  // accounts: []
    }

    func testObservedFreshness() throws {
        let s = try XCTUnwrap(TrunklineState.load(from: good))
        XCTAssertEqual(s.observedFresh(now: 1000), 12.5)
        XCTAssertNil(s.observedFresh(now: 990 + 3601))   // 1h 초과 → nil
    }

    func testParsesClaudeEntry() throws {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": null, "last_event": null},
          "claude": {"login_ok": true, "login_warning": null,
                     "usage": {"seven_day_pct": 12, "resets_at": 1784560000.0, "at": 1784511168.4}}}}
        """
        let s = try XCTUnwrap(TrunklineState.load(from: Data(json.utf8)))
        XCTAssertEqual(s.claude?.usage?.sevenDayPct, 12)
    }

    func testClaudeAbsentIsNil() throws {
        let s = try XCTUnwrap(TrunklineState.load(from: good))
        XCTAssertNil(s.claude)
        XCTAssertEqual(s.codex.active, "personal")   // codex 정상
    }

    func testMalformedClaudeKeepsCodex() throws {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": null, "last_event": null},
          "claude": {"usage": {"seven_day_pct": "boom"}}}}
        """
        let s = try XCTUnwrap(TrunklineState.load(from: Data(json.utf8)))
        XCTAssertNil(s.claude)
        XCTAssertEqual(s.codex.active, "personal")   // codex 생존
    }

    func testClaudeWarning() throws {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": null, "last_event": null},
          "claude": {"login_ok": true, "login_warning": "만료 임박 D-3", "usage": null}}}
        """
        let s = try XCTUnwrap(TrunklineState.load(from: Data(json.utf8)))
        XCTAssertEqual(s.claude?.loginWarning, "만료 임박 D-3")
    }

    func testParsesAccountHealthStatesAndRedactsProviderText() throws {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "account_health": [
            {"label":"a","model":"m","state":"healthy","observed_at":1},
            {"label":"b","model":"m","state":"usage_exhausted","observed_at":2,"reset_at":3},
            {"label":"c","model":"m","state":"entitlement_unavailable","observed_at":4,"error_class":"redacted"},
            {"label":"d","model":"m","state":"auth_stale","observed_at":5},
            {"label":"e","model":"m","state":"temporarily_throttled","observed_at":6},
            {"label":"f","model":"m","state":"unknown","observed_at":7}
          ]}}}
        """
        let health = try XCTUnwrap(TrunklineState.load(from: Data(json.utf8))?.provider.accountHealth)
        XCTAssertEqual(health.map(\.state), [.healthy, .usageExhausted, .entitlementUnavailable,
                                             .authStale, .temporarilyThrottled, .unknown])
        XCTAssertEqual(health[1].resetAt, 3)
        XCTAssertEqual(health[2].errorClass, "redacted")
        XCTAssertFalse(String(describing: health).contains("provider"))
    }

    func testAccountHealthFutureAndMissingOptionalsAreConservative() throws {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "account_health": [{"label":"personal","model":"m","state":"future_state"}, {}]}}}
        """
        let health = try XCTUnwrap(TrunklineState.load(from: Data(json.utf8))?.provider.accountHealth)
        XCTAssertEqual(health.map(\.state), [.unknown, .unknown])
        XCTAssertNil(health[0].observedAt)
        XCTAssertNil(health[1].label)
        XCTAssertNil(health[1].model)
        XCTAssertNil(health[1].errorClass)
    }
}
