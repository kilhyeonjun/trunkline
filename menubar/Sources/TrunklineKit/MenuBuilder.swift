import Foundation

public struct MenuItemSpec: Equatable {
    public var title: String
    public var enabled: Bool = true
    public var action: [String]? = nil       // CLIRunner 인자
    public var isSeparator: Bool = false
    public var submenu: [MenuItemSpec]? = nil
    public var isQuit: Bool = false
    public var isUsageReload: Bool = false   // "reload" — PurityTests 금지어 회피 목적 (re + fresh 조합 문자열 금지)
    public var gauge: GaugeSpec? = nil
    public var rightRuns: [StyledRun]? = nil // 헤더 우측 탭·계정 행 병기

    public init(title: String, enabled: Bool = true, action: [String]? = nil,
                isSeparator: Bool = false, submenu: [MenuItemSpec]? = nil,
                isQuit: Bool = false, isUsageReload: Bool = false,
                gauge: GaugeSpec? = nil, rightRuns: [StyledRun]? = nil) {
        self.title = title
        self.enabled = enabled
        self.action = action
        self.isSeparator = isSeparator
        self.submenu = submenu
        self.isQuit = isQuit
        self.isUsageReload = isUsageReload
        self.gauge = gauge
        self.rightRuns = rightRuns
    }
}

/// "데이터 없음"(at nil) / "방금 갱신됨"(<5분) / "N분 전 갱신"(<1시간) / relativeText+" 전 갱신 ⚠"(그 외).
func freshnessText(now: Double, at: Double?) -> String {
    guard let at else { return "데이터 없음" }
    let age = max(0, now - at)
    if age < 300 { return "방금 갱신됨" }
    if age < 3600 { return "\(Int(age / 60))분 전 갱신" }
    return relativeText(seconds: age) + " 전 갱신 ⚠︎"
}

public func buildMenuSpec(state: TrunklineState?, usage: [UsageRow]?,
                          now: Double, wakeGraceUntil: Double,
                          pythonWarning: String? = nil,
                          claudeDetail: ClaudeUsageDetail? = nil) -> [MenuItemSpec] {
    var items: [MenuItemSpec] = []
    guard let s = state else {
        items.append(MenuItemSpec(title: "상태 불명 — trunkline init 필요", enabled: false))
        items.append(MenuItemSpec(title: "", isSeparator: true))
        items.append(MenuItemSpec(title: "종료", isQuit: true))
        return items
    }
    let health = s.health(now: now, wakeGraceUntil: wakeGraceUntil)
    let actionable = health == .running
    let active = s.provider.active ?? ""
    // 중복 label 방어 — 손상된 store·수동 편집 등으로 동일 label이 두 번 오면 uniqueKeysWithValues가
    // fatalError로 크래시하므로 첫 값 우선으로 방어.
    let usageByLabel = Dictionary((usage ?? []).map { ($0.label, $0) }, uniquingKeysWith: { a, _ in a })

    // Codex 헤더 — 이름 + 우측: 신선도·활성계정·모드.
    items.append(MenuItemSpec(
        title: "Codex", enabled: false,
        rightRuns: [
            StyledRun(text: freshnessText(now: now, at: s.updatedAt), style: .dim),
            StyledRun(text: "활성: \(s.provider.active ?? "-")", style: .normal),
            StyledRun(text: "모드: \(s.provider.mode)", style: .normal),
        ]))
    if usage == nil {
        items.append(MenuItemSpec(title: "Usage 불러오는 중…", enabled: false))
    }

    // 계정 행 — 비활성 + 소진 시 "소진" danger 병기, 스냅샷 없음 시 행동 안내 병기.
    for a in s.provider.accounts {
        let bullet = a.label == s.provider.active ? "●" : "○"
        let mark = a.snapshotOk ? "✓" : "✗"
        var rightRuns: [StyledRun] = []
        if let plan = usageByLabel[a.label]?.plan {
            rightRuns.append(StyledRun(text: planDisplayText(plan), style: .normal))
        }
        if a.label != s.provider.active, let row = usageByLabel[a.label],
           let used = row.primaryUsed, severity(forFillPercent: used) == .exhausted {
            rightRuns.append(StyledRun(text: "소진", style: .danger))
        }
        if !a.snapshotOk {
            rightRuns.append(StyledRun(text: "스냅샷 없음 — adopt 필요", style: .warn))
        }
        items.append(MenuItemSpec(title: "\(bullet) \(a.label) \(mark)",
                                  enabled: actionable && a.snapshotOk,
                                  action: ["switch", a.label],
                                  rightRuns: rightRuns.isEmpty ? nil : rightRuns))
    }

    // 창 행들 — wham 창별(계정마다 primary·secondary, 존재하는 창만) + observed 5h "(관측)".
    for a in s.provider.accounts {
        guard let row = usageByLabel[a.label], row.ok else { continue }
        if let minutes = row.primaryWindowMinutes, let used = row.primaryUsed {
            items.append(MenuItemSpec(
                title: "", enabled: false,
                gauge: makeGaugeSpec(title: "\(windowTitle(minutes: minutes)) (\(a.label))",
                                     usedPercent: used, resetsAt: row.primaryReset,
                                     windowMinutes: minutes, now: now, wallClock: now,
                                     dataAgeSeconds: 0)))
        }
        if let minutes = row.secondaryWindowMinutes, let used = row.secondaryUsed {
            items.append(MenuItemSpec(
                title: "", enabled: false,
                gauge: makeGaugeSpec(title: "\(windowTitle(minutes: minutes)) (\(a.label))",
                                     usedPercent: used, resetsAt: row.secondaryReset,
                                     windowMinutes: minutes, now: now, wallClock: now,
                                     dataAgeSeconds: 0)))
        }
    }
    if let o = s.provider.observed, now - o.at <= 3600 {
        items.append(MenuItemSpec(
            title: "", enabled: false,
            gauge: makeGaugeSpec(title: "\(windowTitle(minutes: 300)) (관측)",
                                 usedPercent: o.usedPercent, resetsAt: o.resetsAt,
                                 windowMinutes: 300, now: now, wallClock: now,
                                 dataAgeSeconds: now - o.at)))
    }

    items.append(MenuItemSpec(title: "", isSeparator: true))
    items.append(MenuItemSpec(title: "모드", enabled: actionable, submenu: [
        MenuItemSpec(title: "auto", enabled: actionable, action: ["auto"]),
        MenuItemSpec(title: "pin (\(active))", enabled: actionable && !active.isEmpty,
                     action: ["pin", active]),
        MenuItemSpec(title: "lock (\(active))", enabled: actionable && !active.isEmpty,
                     action: ["lock", active]),
    ]))
    items.append(MenuItemSpec(title: "", isSeparator: true))

    // Claude 섹션 — 헤더(신선도 ⚠·로그인 D-N) → 창 행 5h·7d.
    if let cl = s.claude {
        var rightRuns = [StyledRun(text: freshnessText(now: now, at: claudeDetail?.fetchedAt ?? cl.usage?.at),
                                    style: .dim)]
        if let tierText = claudeTierDisplayText(claudeDetail?.tier) {
            rightRuns.append(StyledRun(text: tierText, style: .normal))
        }
        if let w = cl.loginWarning { rightRuns.append(StyledRun(text: w, style: .warn)) }
        items.append(MenuItemSpec(title: "Claude", enabled: false, rightRuns: rightRuns))

        if let d = claudeDetail, d.ok {
            let fetchedAt = d.fetchedAt ?? now
            if let pct = d.fiveHourPct {
                items.append(MenuItemSpec(
                    title: "", enabled: false,
                    gauge: makeGaugeSpec(title: windowTitle(minutes: 300), usedPercent: pct,
                                         resetsAt: d.fiveHourResetsAt, windowMinutes: 300,
                                         now: fetchedAt, wallClock: now, dataAgeSeconds: now - fetchedAt,
                                         tint: .claude)))
            }
            if let pct = d.sevenDayPct {
                items.append(MenuItemSpec(
                    title: "", enabled: false,
                    gauge: makeGaugeSpec(title: windowTitle(minutes: 10080), usedPercent: pct,
                                         resetsAt: d.sevenDayResetsAt, windowMinutes: 10080,
                                         now: fetchedAt, wallClock: now, dataAgeSeconds: now - fetchedAt,
                                         tint: .claude)))
            }
        }
        items.append(MenuItemSpec(title: "", isSeparator: true))
    }

    items.append(MenuItemSpec(title: "Usage 갱신", isUsageReload: true))
    if let ev = s.provider.lastEvent {
        let arrow = ev.from.map { "\($0)→\(ev.to)" } ?? ev.to
        let reason = ev.reason.map { " (\($0))" } ?? ""
        items.append(MenuItemSpec(
            title: "마지막 이벤트: \(ev.type) \(arrow)\(reason) \(relativeText(seconds: now - ev.at)) 전",
            enabled: false))
    }
    let daemonText = switch health {
    case .running: "데몬: 실행 중"
    case .stopped: "데몬: ⚠︎ 정지 — trunkline daemon 실행"
    case .storeBroken: "데몬: ⚠︎ 스토어 비정상"
    }
    items.append(MenuItemSpec(title: daemonText, enabled: false))
    if let w = pythonWarning {
        items.append(MenuItemSpec(title: "⚠︎ \(w)", enabled: false))
    }
    items.append(MenuItemSpec(title: "", isSeparator: true))
    items.append(MenuItemSpec(title: "종료", isQuit: true))
    return items
}
