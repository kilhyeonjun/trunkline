import XCTest
@testable import TrunklineKit

final class PlanDisplayTests: XCTestCase {
    // codex plan 원문 → 표시 매핑: pro/plus/free/team → 고정 표기, 그 외 원문 첫글자 대문자
    func testCodexPlanDisplayTextKnownValues() {
        XCTAssertEqual(planDisplayText("pro"), "Pro")
        XCTAssertEqual(planDisplayText("plus"), "Plus")
        XCTAssertEqual(planDisplayText("free"), "Free")
        XCTAssertEqual(planDisplayText("team"), "Team")
    }

    func testCodexPlanDisplayTextUnknownCapitalizesFirstLetter() {
        XCTAssertEqual(planDisplayText("enterprise"), "Enterprise")
        XCTAssertEqual(planDisplayText("x"), "X")
    }

    // claude tier 매핑 — 알려진 3케이스 + 매핑 불가는 nil(원문 노출 금지)
    func testClaudeTierDisplayTextKnownValues() {
        XCTAssertEqual(claudeTierDisplayText("default_claude_max_20x"), "Max 20x")
        XCTAssertEqual(claudeTierDisplayText("default_claude_max_5x"), "Max 5x")
        XCTAssertEqual(claudeTierDisplayText("default_claude_pro"), "Pro")
    }

    func testClaudeTierDisplayTextUnmappedReturnsNilNotRawIdentifier() {
        XCTAssertNil(claudeTierDisplayText("some_internal_id"))
        XCTAssertNil(claudeTierDisplayText(nil))
    }
}
