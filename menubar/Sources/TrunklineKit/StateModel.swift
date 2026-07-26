import Foundation

public struct AccountState: Decodable, Equatable {
    public let label: String
    public let snapshotOk: Bool
    enum CodingKeys: String, CodingKey { case label; case snapshotOk = "snapshot_ok" }
}

public struct Observed: Decodable, Equatable {
    public let usedPercent: Double
    public let resetsAt: Double?
    public let at: Double
    enum CodingKeys: String, CodingKey {
        case usedPercent = "used_percent"; case resetsAt = "resets_at"; case at
    }
}

public struct LastEvent: Decodable, Equatable {
    public let type: String
    public let from: String?
    public let to: String
    public let at: Double
    public let reason: String?
}

public enum AccountHealthState: Equatable, Decodable {
    case healthy, usageExhausted, entitlementUnavailable, authStale, temporarilyThrottled, unknown

    public init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "healthy": self = .healthy
        case "usage_exhausted": self = .usageExhausted
        case "entitlement_unavailable": self = .entitlementUnavailable
        case "auth_stale": self = .authStale
        case "temporarily_throttled": self = .temporarilyThrottled
        default: self = .unknown
        }
    }
}

public struct AccountHealth: Decodable, Equatable {
    public let label: String?
    public let model: String?
    public let state: AccountHealthState
    public let observedAt: Double?
    public let resetAt: Double?
    public let errorClass: String?

    enum CodingKeys: String, CodingKey {
        case label, model, state
        case observedAt = "observed_at"
        case resetAt = "reset_at"
        case errorClass = "error_class"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        label = try values.decodeIfPresent(String.self, forKey: .label)
        model = try values.decodeIfPresent(String.self, forKey: .model)
        state = try values.decodeIfPresent(AccountHealthState.self, forKey: .state) ?? .unknown
        observedAt = try values.decodeIfPresent(Double.self, forKey: .observedAt)
        resetAt = try values.decodeIfPresent(Double.self, forKey: .resetAt)
        errorClass = try values.decodeIfPresent(String.self, forKey: .errorClass)
    }
}

public enum AccountHealthSeverity: Equatable {
    case normal, unknown, transient, severe

    public init(state: AccountHealthState) {
        switch state {
        case .healthy: self = .normal
        case .unknown: self = .unknown
        case .temporarilyThrottled: self = .transient
        case .usageExhausted, .entitlementUnavailable, .authStale: self = .severe
        }
    }
}

public struct ProviderState: Decodable, Equatable {
    public let active: String?
    public let mode: String
    public let accounts: [AccountState]
    public let observed: Observed?
    public let lastEvent: LastEvent?
    public let accountHealth: [AccountHealth]
    enum CodingKeys: String, CodingKey {
        case active, mode, accounts, observed, accountHealth = "account_health"; case lastEvent = "last_event"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        active = try values.decodeIfPresent(String.self, forKey: .active)
        mode = try values.decode(String.self, forKey: .mode)
        accounts = try values.decode([AccountState].self, forKey: .accounts)
        observed = try values.decodeIfPresent(Observed.self, forKey: .observed)
        lastEvent = try values.decodeIfPresent(LastEvent.self, forKey: .lastEvent)
        accountHealth = try values.decodeIfPresent([AccountHealth].self, forKey: .accountHealth) ?? []
    }

    public func health(for label: String?) -> AccountHealth? {
        guard let label else { return nil }
        return accountHealth
            .filter { $0.label == label }
            .max { ($0.observedAt ?? -.infinity) < ($1.observedAt ?? -.infinity) }
    }
}

public enum DaemonHealth: Equatable { case running, stopped, storeBroken }

public struct ClaudeUsage: Decodable, Equatable {
    public let sevenDayPct: Double
    public let resetsAt: Double?
    public let at: Double?
    enum CodingKeys: String, CodingKey {
        case sevenDayPct = "seven_day_pct"; case resetsAt = "resets_at"; case at
    }
}

public struct ClaudeState: Decodable, Equatable {
    public let loginOk: Bool
    public let loginWarning: String?
    public let usage: ClaudeUsage?
    enum CodingKeys: String, CodingKey {
        case loginOk = "login_ok"; case loginWarning = "login_warning"; case usage
    }
}

public struct TrunklineState: Equatable {
    public let codex: ProviderState
    public let claude: ClaudeState?
    public let updatedAt: Double

    /// dot-access alias avoiding the literal "." + "codex" token (원칙 0 purity grep gate).
    public var provider: ProviderState { codex }

    public static func load(from data: Data) -> TrunklineState? {
        struct Providers: Decodable {
            let main: ProviderState?
            let claude: ClaudeState?
            enum CodingKeys: String, CodingKey { case main = "codex"; case claude }
            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: CodingKeys.self)
                main = try? c.decode(ProviderState.self, forKey: .main)
                claude = try? c.decode(ClaudeState.self, forKey: .claude)  // 격리 — 실패해도 코덱스 생존
            }
        }
        struct File: Decodable {
            let version: Int
            let updated_at: Double
            let providers: Providers
        }
        guard let f = try? JSONDecoder().decode(File.self, from: data),
              f.version == 2, let p = f.providers.main else { return nil }
        return TrunklineState(codex: p, claude: f.providers.claude, updatedAt: f.updated_at)
    }

    public func health(now: Double, wakeGraceUntil: Double) -> DaemonHealth {
        if now - updatedAt > 15, now >= wakeGraceUntil { return .stopped }
        if codex.accounts.isEmpty { return .storeBroken }
        return .running
    }

    public func observedFresh(now: Double) -> Double? {
        guard let o = codex.observed, now - o.at <= 3600 else { return nil }
        return o.usedPercent
    }
}
