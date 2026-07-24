import Foundation

public struct UsageRow: Decodable, Equatable {
    public let label: String
    public let ok: Bool
    public let stale: Bool
    public let primaryUsed: Double?
    public let secondaryUsed: Double?
    public let error: String?
    /// T2 신규 필드 — wham `limit_window_seconds`//60 유래, 창 없으면 nil.
    public let primaryWindowMinutes: Int?
    public let secondaryWindowMinutes: Int?
    public let primaryReset: Double?
    public let secondaryReset: Double?
    /// T6b — 계정 구독 플랜(identity `chatgpt_plan_type` 유래). 미상은 nil.
    public let plan: String?
    enum CodingKeys: String, CodingKey {
        case label, ok, stale, error, plan
        case primaryUsed = "primary_used"; case secondaryUsed = "secondary_used"
        case primaryWindowMinutes = "primary_window_minutes"
        case secondaryWindowMinutes = "secondary_window_minutes"
        case primaryReset = "primary_reset"; case secondaryReset = "secondary_reset"
    }

    public init(label: String, ok: Bool, stale: Bool,
                primaryUsed: Double?, secondaryUsed: Double?, error: String?,
                primaryWindowMinutes: Int? = nil, secondaryWindowMinutes: Int? = nil,
                primaryReset: Double? = nil, secondaryReset: Double? = nil,
                plan: String? = nil) {
        self.label = label
        self.ok = ok
        self.stale = stale
        self.primaryUsed = primaryUsed
        self.secondaryUsed = secondaryUsed
        self.error = error
        self.primaryWindowMinutes = primaryWindowMinutes
        self.secondaryWindowMinutes = secondaryWindowMinutes
        self.primaryReset = primaryReset
        self.secondaryReset = secondaryReset
        self.plan = plan
    }
}

public struct ClaudeUsageDetail: Decodable, Equatable {
    public let ok: Bool
    public let fiveHourPct: Double?
    public let fiveHourResetsAt: Double?
    public let sevenDayPct: Double?
    public let sevenDayResetsAt: Double?
    public let fetchedAt: Double?
    public let error: String?
    /// T6b — 구독 티어 원문 식별자(예: "default_claude_max_20x"). 표시는 claudeTierDisplayText 경유.
    public let tier: String?
    enum CodingKeys: String, CodingKey {
        case ok, error, tier
        case fiveHourPct = "five_hour_pct"; case fiveHourResetsAt = "five_hour_resets_at"
        case sevenDayPct = "seven_day_pct"; case sevenDayResetsAt = "seven_day_resets_at"
        case fetchedAt = "fetched_at"
    }

    public init(ok: Bool, fiveHourPct: Double?, fiveHourResetsAt: Double?,
                sevenDayPct: Double?, sevenDayResetsAt: Double?,
                fetchedAt: Double?, error: String?, tier: String? = nil) {
        self.ok = ok
        self.fiveHourPct = fiveHourPct
        self.fiveHourResetsAt = fiveHourResetsAt
        self.sevenDayPct = sevenDayPct
        self.sevenDayResetsAt = sevenDayResetsAt
        self.fetchedAt = fetchedAt
        self.error = error
        self.tier = tier
    }
}

public struct UsageReport: Equatable {
    public let rows: [UsageRow]
    public let claude: ClaudeUsageDetail?
    public init(rows: [UsageRow], claude: ClaudeUsageDetail?) {
        self.rows = rows; self.claude = claude
    }

    public static func decode(_ data: Data) -> UsageReport? {
        struct New: Decodable {
            let main: [UsageRow]; let claude: ClaudeUsageDetail?
            enum CodingKeys: String, CodingKey { case main = "codex"; case claude }
        }
        if let n = try? JSONDecoder().decode(New.self, from: data) {
            return UsageReport(rows: n.main, claude: n.claude)
        }
        return nil
    }
}
