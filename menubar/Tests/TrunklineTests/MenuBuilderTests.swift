import XCTest
@testable import TrunklineKit

final class MenuBuilderTests: XCTestCase {
    let goodJSON = """
    {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
      "active": "personal", "mode": "auto",
      "accounts": [{"label": "personal", "snapshot_ok": true},
                   {"label": "company", "snapshot_ok": false}],
      "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
      "last_event": {"type": "fallback", "from": "personal", "to": "company",
                     "at": 900.0, "reason": "personal exhausted"}}}}
    """

    func state(_ json: String) -> TrunklineState {
        TrunklineState.load(from: Data(json.utf8))!
    }

    // 1. 섹션 순서: Codex 헤더 → 로딩(usage nil) → 계정 행 → 창 행(observed) → sep → 모드 → sep →
    //    Usage 갱신/이벤트/데몬 → sep → 종료 (usage nil, claude nil인 최소 케이스)
    // H — 로딩 행이 메뉴 하단이 아니라 Codex 헤더 직하로 이동.
    func testSectionOrderMinimalState() {
        let s = state(goodJSON)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)

        XCTAssertEqual(items[0].title, "Codex")
        XCTAssertFalse(items[0].enabled)
        XCTAssertNotNil(items[0].rightRuns)

        XCTAssertEqual(items[1].title, "Usage 불러오는 중…")

        XCTAssertEqual(items[2].title, "● personal ✓")
        XCTAssertEqual(items[3].title, "○ company ✗")

        // observed 5h (990, TTL 1h 이내) → 게이지 행
        let observedGauge = items[4]
        XCTAssertNotNil(observedGauge.gauge)
        XCTAssertTrue(observedGauge.gauge!.title.contains("(관측)"))
        XCTAssertNil(observedGauge.gauge!.title.range(of: "personal"))

        XCTAssertTrue(items[5].isSeparator)

        let modeItem = items[6]
        XCTAssertEqual(modeItem.title, "모드")
        XCTAssertEqual(modeItem.submenu?.count, 3)

        XCTAssertTrue(items[7].isSeparator)

        // claude 없음 → 바로 꼬리(로딩 행은 이미 헤더 직하로 이동했으므로 여기는 Usage 갱신부터)
        XCTAssertTrue(items[8].isUsageReload)
        XCTAssertEqual(items[8].title, "Usage 갱신")

        let eventItem = items.first { $0.title.hasPrefix("마지막 이벤트:") }
        XCTAssertNotNil(eventItem)
        // now(1000) - ev.at(900) = 100s → relativeText "1분"
        XCTAssertEqual(eventItem?.title, "마지막 이벤트: fallback personal→company (personal exhausted) 1분 전")

        XCTAssertTrue(items.contains { $0.title == "데몬: 실행 중" })

        XCTAssertEqual(items.last?.title, "종료")
        XCTAssertTrue(items.last?.isQuit ?? false)
    }

    // 2. 계정 행 액션 — 기존 계약 회귀 금지
    func testAccountRowActions() {
        let s = state(goodJSON)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)

        let personalRow = items.first { $0.title.contains("personal") && $0.action != nil }
        XCTAssertEqual(personalRow?.action, ["switch", "personal"])
        XCTAssertTrue(personalRow?.enabled ?? false)

        let companyRow = items.first { $0.title.hasPrefix("○ company") }
        XCTAssertEqual(companyRow?.title, "○ company ✗")
        XCTAssertFalse(companyRow?.enabled ?? true)   // snapshot_ok false → 비활성
    }

    // 3. 모드 서브메뉴 — 회귀 금지
    func testModeSubmenuActions() {
        let s = state(goodJSON)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)
        let modeItem = items.first { $0.title == "모드" }!
        let submenu = modeItem.submenu!

        XCTAssertEqual(submenu[0].action, ["auto"])
        XCTAssertEqual(submenu[1].action, ["pin", "personal"])
        XCTAssertEqual(submenu[1].title, "pin (personal)")
        XCTAssertEqual(submenu[2].action, ["lock", "personal"])
        XCTAssertEqual(submenu[2].title, "lock (personal)")
    }

    // 4. 데몬 정지 상태: switch/pin/lock 전부 enabled == false — 회귀 금지
    func testStoppedDaemonDisablesAllActions() {
        let s = state(goodJSON)
        // updated_at 1000, now 1020 → 20s 경과 > 15s, wakeGraceUntil 0 → stopped
        let items = buildMenuSpec(state: s, usage: nil, now: 1020, wakeGraceUntil: 0)

        let accountRows = items.filter { $0.action?.first == "switch" }
        XCTAssertFalse(accountRows.isEmpty)
        for row in accountRows { XCTAssertFalse(row.enabled) }

        let modeItem = items.first { $0.title == "모드" }!
        XCTAssertFalse(modeItem.enabled)
        for sub in modeItem.submenu! { XCTAssertFalse(sub.enabled) }

        XCTAssertTrue(items.contains { $0.title == "데몬: ⚠︎ 정지 — trunkline daemon 실행" })
    }

    // 5. 계정 창 행 — wham 창별 게이지, "존재하는 창만"(secondary 없음 → 행 없음)
    func testAccountWindowGaugeRows() {
        let s = state(goodJSON)
        let row = UsageRow(label: "personal", ok: true, stale: false,
                            primaryUsed: 12.4, secondaryUsed: nil, error: nil,
                            primaryWindowMinutes: 10080, secondaryWindowMinutes: nil,
                            primaryReset: 2000.0, secondaryReset: nil)
        let items = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)

        let gauges = items.compactMap(\.gauge)
        let personalGauge = gauges.first { $0.title.contains("personal") }
        XCTAssertNotNil(personalGauge)
        XCTAssertEqual(personalGauge?.title, "주간 · 7일 창 (personal)")
        XCTAssertEqual(personalGauge?.fillPercent, 12.4)

        // secondary 없음(secondaryWindowMinutes nil) → secondary 창 행 없음(observed(관측)만 별개로 존재)
        let secondaryLikeCount = gauges.filter { $0.title.contains("personal") }.count
        XCTAssertEqual(secondaryLikeCount, 1)
    }

    // 6. 계정 게이지 severity·값 — 소진 fill>=100
    func testAccountWindowGaugeExhaustedSeverity() {
        let s = state(goodJSON)
        let row = UsageRow(label: "personal", ok: true, stale: false,
                            primaryUsed: 100, secondaryUsed: nil, error: nil,
                            primaryWindowMinutes: 300, secondaryWindowMinutes: nil,
                            primaryReset: 2000.0, secondaryReset: nil)
        let items = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)
        let gauge = items.compactMap(\.gauge).first { $0.title.contains("personal") }
        XCTAssertEqual(gauge?.severity, .exhausted)
        XCTAssertEqual(gauge?.tint, .main)
    }

    // 7. 비활성 계정 소진 시 rightRuns "소진" danger 병기 (N — "— 소진"에서 줄표 제거).
    //    goodJSON의 company는 snapshot_ok:false → K의 "스냅샷 없음" warn run도 함께 병기.
    func testInactiveAccountExhaustedRightRuns() {
        let s = state(goodJSON)
        let row = UsageRow(label: "company", ok: true, stale: false,
                            primaryUsed: 100, secondaryUsed: nil, error: nil,
                            primaryWindowMinutes: 300, secondaryWindowMinutes: nil,
                            primaryReset: nil, secondaryReset: nil)
        let items = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)
        let companyRow = items.first { $0.title.hasPrefix("○ company") }
        XCTAssertEqual(companyRow?.rightRuns, [
            StyledRun(text: "소진", style: .danger),
            StyledRun(text: "스냅샷 없음 — adopt 필요", style: .warn),
        ])

        // 활성 계정(personal)은 usage 없음 → rightRuns nil
        let personalRow = items.first { $0.title.hasPrefix("● personal") }
        XCTAssertNil(personalRow?.rightRuns)
    }

    // 8. observed 5h TTL 1시간 초과 → 행 생략
    func testObservedRowOmittedWhenStale() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 900.0}}}}
        """
        // now - at = 3601 > 3600 → 생략
        let items = buildMenuSpec(state: state(json), usage: nil, now: 4501, wakeGraceUntil: 0)
        XCTAssertFalse(items.contains { $0.gauge?.title.contains("관측") ?? false })
    }

    // 9. Codex 헤더 신선도 문자열 — F: 방금 갱신됨(<5분)/N분 전 갱신(<1시간)/relativeText 전 갱신 ⚠︎(그 외)
    func testCodexHeaderFreshnessStrings() {
        let s = state(goodJSON)   // updated_at 1000
        let fresh = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)
        XCTAssertEqual(fresh[0].rightRuns?.first?.text, "방금 갱신됨")

        let stale = buildMenuSpec(state: s, usage: nil, now: 1000 + 3 * 3600, wakeGraceUntil: 0)
        XCTAssertEqual(stale[0].rightRuns?.first?.text, "3시간 전 갱신 ⚠︎")
    }

    // F — freshnessText(at: nil) → "데이터 없음"(과거 "방금 업데이트됨" 거짓 신선도 표기 제거).
    // Claude 헤더가 fetchedAt·usage.at 모두 nil인 미수집 상태에서 재현.
    func testClaudeHeaderFreshnessNilShowsNoDataInsteadOfFalseFresh() {
        let s = stateWithClaude("""
        {"login_ok": true, "login_warning": null, "usage": null}
        """)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)
        let claudeHeader = items.first { $0.title == "Claude" }
        XCTAssertEqual(claudeHeader?.rightRuns?.first?.text, "데이터 없음")
        XCTAssertEqual(claudeHeader?.rightRuns?.first?.style, .dim)
    }

    // 10. state nil → 상태 불명 표시 + 액션 전부 비활성 — 회귀 금지
    func testNilStateShowsUnknownAndDisablesActions() {
        let items = buildMenuSpec(state: nil, usage: nil, now: 1000, wakeGraceUntil: 0)

        XCTAssertEqual(items[0].title, "상태 불명 — trunkline init 필요")
        XCTAssertFalse(items[0].enabled)
        XCTAssertTrue(items[1].isSeparator)
        XCTAssertEqual(items[2].title, "종료")
        XCTAssertTrue(items[2].isQuit)

        for item in items {
            XCTAssertNil(item.action)
        }
    }

    // claude JSON — good state + claude 엔트리 부착본
    func stateWithClaude(_ claudeJSON: String) -> TrunklineState {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true},
                       {"label": "company", "snapshot_ok": false}],
          "observed": {"used_percent": 12.5, "resets_at": 2000.0, "at": 990.0},
          "last_event": {"type": "fallback", "from": "personal", "to": "company",
                         "at": 900.0, "reason": "personal exhausted"}},
          "claude": \(claudeJSON)}}
        """
        return TrunklineState.load(from: Data(json.utf8))!
    }

    // 11. claude 섹션 — 헤더 "Claude"(rightRuns) + 전 claude 행 action == nil && !isQuit && !isUsageReload
    func testClaudeSectionRows() {
        let s = stateWithClaude("""
        {"login_ok": true, "login_warning": null, "usage": {"seven_day_pct": 12, "resets_at": null, "at": null}}
        """)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)

        let claudeHeader = items.first { $0.title == "Claude" }
        XCTAssertNotNil(claudeHeader)
        XCTAssertFalse(claudeHeader!.enabled)

        let headerIdx = items.firstIndex { $0.title == "Claude" }!
        let tailSepIdx = items[headerIdx...].firstIndex { $0.isSeparator }!
        for row in items[headerIdx..<tailSepIdx] {
            XCTAssertNil(row.action)
            XCTAssertFalse(row.isQuit)
            XCTAssertFalse(row.isUsageReload)
        }
    }

    // 12. claude loginWarning → 헤더 rightRuns에 "만료 임박 D-3" 병기
    func testClaudeHeaderLoginWarningRightRuns() {
        let s = stateWithClaude("""
        {"login_ok": true, "login_warning": "만료 임박 D-3", "usage": null}
        """)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)

        let claudeHeader = items.first { $0.title == "Claude" }
        XCTAssertTrue(claudeHeader?.rightRuns?.contains(StyledRun(text: "만료 임박 D-3", style: .warn)) ?? false)
    }

    // 13. claude nil → "Claude" 헤더 없음 — 회귀 금지
    func testClaudeSectionAbsent() {
        let s = state(goodJSON)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)
        XCTAssertFalse(items.contains { $0.title == "Claude" })
    }

    // 14. claude 창 행 5h·7d — pace now=fetched_at 결선(렌더 now와 분리됨을 값으로 검증)
    func testClaudeWindowRowsUseFetchedAtForPaceNow() {
        let s = stateWithClaude("""
        {"login_ok": true, "login_warning": null, "usage": {"seven_day_pct": 26, "resets_at": null, "at": 0}}
        """)
        // 브리프 7일 창 예시: used=26, resetsAt=+105h(절대 105*3600), fetchedAt=0 == pace now.
        // 렌더 now=1000(fetchedAt과 다른 값)을 pace now로 잘못 쓰면 expected가 37.5에서
        // 벗어나 실패한다 — fetchedAt(0)을 pace now로 써야 브리프 예시와 동일한 expected=37.5가 나온다.
        let resetsAt = 105 * 3600.0
        let detail = ClaudeUsageDetail(ok: true, fiveHourPct: nil, fiveHourResetsAt: nil,
                                        sevenDayPct: 26, sevenDayResetsAt: resetsAt,
                                        fetchedAt: 0, error: nil)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0, claudeDetail: detail)
        let sevenDayGauge = items.compactMap(\.gauge).first { $0.title.contains("7일") }
        XCTAssertNotNil(sevenDayGauge)
        XCTAssertEqual(sevenDayGauge!.expectedPercent!, 37.5, accuracy: 0.0001)
        XCTAssertEqual(sevenDayGauge?.bucket, .reserve)
        XCTAssertEqual(sevenDayGauge?.tint, .claude)
    }

    // 15. claude fiveHourPct nil → 5h 게이지 행 없음(존재하는 창만). codex observed(관측)도 "5시간"을
    //     포함하므로 관측이 없는 state로 격리해 claude 게이지만 검사한다.
    func testClaudeMissingFiveHourPctOmitsGauge() {
        let json = """
        {"version": 2, "updated_at": 1000.0, "providers": {"codex": {
          "active": "personal", "mode": "auto",
          "accounts": [{"label": "personal", "snapshot_ok": true}]},
          "claude": {"login_ok": true, "login_warning": null, "usage": null}}}
        """
        let s = state(json)
        let detail = ClaudeUsageDetail(ok: true, fiveHourPct: nil, fiveHourResetsAt: nil,
                                        sevenDayPct: 12, sevenDayResetsAt: nil,
                                        fetchedAt: 1000, error: nil)
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0, claudeDetail: detail)
        XCTAssertFalse(items.compactMap(\.gauge).contains { $0.tint == .claude && $0.title.contains("5시간") })
        XCTAssertTrue(items.compactMap(\.gauge).contains { $0.tint == .claude && $0.title.contains("7일") })
    }

    // 16. usage --json 신형 디코드 — rows + claude detail
    func testUsageReportDecodeNewShape() throws {
        let json = """
        {"codex": [{"label": "personal", "ok": true, "stale": false,
                    "primary_used": 12.4, "secondary_used": 3.2, "error": null}],
         "claude": {"ok": true, "five_hour_pct": 0, "five_hour_resets_at": null,
                    "seven_day_pct": 12, "seven_day_resets_at": null,
                    "fetched_at": 1000.0, "error": null}}
        """
        let report = try XCTUnwrap(UsageReport.decode(Data(json.utf8)))
        XCTAssertEqual(report.rows.map(\.label), ["personal"])
        XCTAssertEqual(report.claude?.sevenDayPct, 12)
    }

    // 17. T2 신규 필드 — primary/secondary window_minutes·reset 디코드 (R — decodeRows 삭제,
    //     UsageReport.decode 경유로 이전)
    func testUsageRowDecodesWindowMinutesAndResets() throws {
        let json = """
        {"codex": [{"label": "personal", "ok": true, "stale": false,
          "primary_used": 12.4, "primary_reset": 2000.0, "primary_window_minutes": 10080,
          "secondary_used": 3.2, "secondary_reset": 3000.0, "secondary_window_minutes": 300,
          "error": null}]}
        """
        let report = try XCTUnwrap(UsageReport.decode(Data(json.utf8)))
        let row = report.rows[0]
        XCTAssertEqual(row.primaryWindowMinutes, 10080)
        XCTAssertEqual(row.secondaryWindowMinutes, 300)
        XCTAssertEqual(row.primaryReset, 2000.0)
        XCTAssertEqual(row.secondaryReset, 3000.0)
    }

    // 18. 창 필드 없음(구형 wham 응답) → nil 폴백 (R — UsageReport.decode 경유로 이전)
    func testUsageRowMissingWindowFieldsFallsBackToNil() throws {
        let json = """
        {"codex": [{"label": "personal", "ok": true, "stale": false,
          "primary_used": 12.4, "secondary_used": 3.2, "error": null}]}
        """
        let report = try XCTUnwrap(UsageReport.decode(Data(json.utf8)))
        let row = report.rows[0]
        XCTAssertNil(row.primaryWindowMinutes)
        XCTAssertNil(row.secondaryWindowMinutes)
        XCTAssertNil(row.primaryReset)
        XCTAssertNil(row.secondaryReset)
    }

    // 20. usage nil → "Usage 불러오는 중…" 행(Codex 헤더 직하), usage 존재 → 없음 (H)
    func testUsageLoadingRowPresenceTiedToUsageNil() {
        let s = state(goodJSON)
        let loading = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0)
        XCTAssertTrue(loading.contains { $0.title == "Usage 불러오는 중…" })

        let row = UsageRow(label: "personal", ok: true, stale: false,
                            primaryUsed: 12.4, secondaryUsed: nil, error: nil)
        let loaded = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)
        XCTAssertFalse(loaded.contains { $0.title == "Usage 불러오는 중…" })
    }

    // 21. 계정 행 — plan 병기 "· Pro" (T6b)
    func testAccountRowShowsPlan() {
        let s = state(goodJSON)
        let row = UsageRow(label: "personal", ok: true, stale: false,
                            primaryUsed: 12.4, secondaryUsed: nil, error: nil, plan: "pro")
        let items = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)
        let personalRow = items.first { $0.title.hasPrefix("● personal") }
        XCTAssertEqual(personalRow?.rightRuns, [StyledRun(text: "Pro", style: .normal)])
    }

    // 22. plan 병기 + "소진" danger 공존 — joinedRightRunsText 한 줄 병합 경유(N — "— 소진"→"소진").
    //     goodJSON의 company는 snapshot_ok:false → K의 "스냅샷 없음" warn run도 함께 병기.
    func testAccountRowPlanCoexistsWithExhaustedDanger() {
        let s = state(goodJSON)
        let row = UsageRow(label: "company", ok: true, stale: false,
                            primaryUsed: 100, secondaryUsed: nil, error: nil,
                            primaryWindowMinutes: 300, plan: "plus")
        let items = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)
        let companyRow = items.first { $0.title.hasPrefix("○ company") }
        XCTAssertEqual(companyRow?.rightRuns, [
            StyledRun(text: "Plus", style: .normal),
            StyledRun(text: "소진", style: .danger),
            StyledRun(text: "스냅샷 없음 — adopt 필요", style: .warn),
        ])
        let joined = joinedRightRunsText(companyRow!.rightRuns!)
        XCTAssertEqual(joined.text, "Plus · 소진 · 스냅샷 없음 — adopt 필요")
        XCTAssertEqual(joined.style, .danger)   // danger 우선순위 유지 — 회귀 금지
    }

    // 23. plan 없음(nil) → rightRuns 부착 없음 — 회귀 금지
    func testAccountRowNoPlanNoRightRuns() {
        let s = state(goodJSON)
        let row = UsageRow(label: "personal", ok: true, stale: false,
                            primaryUsed: 12.4, secondaryUsed: nil, error: nil)
        let items = buildMenuSpec(state: s, usage: [row], now: 1000, wakeGraceUntil: 0)
        let personalRow = items.first { $0.title.hasPrefix("● personal") }
        XCTAssertNil(personalRow?.rightRuns)
    }

    // 24. Claude 헤더 — tier 표기 병기 (알려진 매핑)
    func testClaudeHeaderShowsTierText() {
        let s = stateWithClaude("""
        {"login_ok": true, "login_warning": null, "usage": null}
        """)
        let detail = ClaudeUsageDetail(ok: true, fiveHourPct: nil, fiveHourResetsAt: nil,
                                        sevenDayPct: nil, sevenDayResetsAt: nil,
                                        fetchedAt: nil, error: nil, tier: "default_claude_max_20x")
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0, claudeDetail: detail)
        let claudeHeader = items.first { $0.title == "Claude" }
        XCTAssertTrue(claudeHeader?.rightRuns?.contains(StyledRun(text: "Max 20x", style: .normal)) ?? false)
    }

    // 25. Claude 헤더 — tier 매핑 불가 → 표기 생략(원문 노출 금지), 나머지 rightRuns는 유지
    func testClaudeHeaderOmitsUnmappableTier() {
        let s = stateWithClaude("""
        {"login_ok": true, "login_warning": null, "usage": null}
        """)
        let detail = ClaudeUsageDetail(ok: true, fiveHourPct: nil, fiveHourResetsAt: nil,
                                        sevenDayPct: nil, sevenDayResetsAt: nil,
                                        fetchedAt: nil, error: nil, tier: "some_internal_id")
        let items = buildMenuSpec(state: s, usage: nil, now: 1000, wakeGraceUntil: 0, claudeDetail: detail)
        let claudeHeader = items.first { $0.title == "Claude" }
        XCTAssertFalse(claudeHeader?.rightRuns?.contains { $0.text == "some_internal_id" } ?? false)
        XCTAssertFalse(claudeHeader?.rightRuns?.contains { $0.text.contains("_") } ?? false)
    }
}
