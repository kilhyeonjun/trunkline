import Foundation

/// 메뉴바 타이틀. %는 잔여율(100-used_percent) — 메뉴 내부 "N% 남음"과 방향 통일.
public func statusTitle(state: TrunklineState?, now: Double, wakeGraceUntil: Double) -> String {
    guard let s = state else { return "⚠︎?" }
    switch s.health(now: now, wakeGraceUntil: wakeGraceUntil) {
    case .stopped: return "⚠︎"
    case .storeBroken: return "⚠︎!"
    case .running: break
    }
    let (active, lastEvent) = (s.provider.active, s.provider.lastEvent)
    if let accountHealth = s.provider.health(for: active) {
        switch AccountHealthSeverity(state: accountHealth.state) {
        case .severe: return "⚠︎!"
        case .transient: return "⏳"
        case .unknown: return "⚠︎?"
        case .normal: break
        }
    }
    let label = active.map { String($0.prefix(1)).uppercased() } ?? "?"
    let recentFallback = lastEvent.map { $0.type == "fallback" && now - $0.at < 600 } ?? false
    let prefix = recentFallback ? "⇄" : ""
    let claudeSuffix = (s.claude?.loginWarning != nil) ? "·C⚠︎" : ""
    if let pct = s.observedFresh(now: now) {
        return "\(prefix)\(label) \(Int((100 - pct).rounded()))%\(claudeSuffix)"
    }
    return "\(prefix)\(label)\(claudeSuffix)"
}

/// 상태 버튼 VoiceOver 레이블 — statusTitle의 축약 기호(이니셜·%·⚠︎)를 풀어 쓴 문장으로.
public func statusAccessibilityLabel(state: TrunklineState?, now: Double, wakeGraceUntil: Double) -> String {
    guard let s = state else { return "Trunkline — 상태 불명" }
    switch s.health(now: now, wakeGraceUntil: wakeGraceUntil) {
    case .stopped: return "Trunkline — 데몬 정지"
    case .storeBroken: return "Trunkline — 스토어 비정상"
    case .running: break
    }
    let active = s.provider.active ?? "없음"
    if let accountHealth = s.provider.health(for: s.provider.active) {
        return "Trunkline — 활성 \(active), 계정 상태 \(accountHealthText(accountHealth.state))"
    }
    let claudeSuffix = (s.claude?.loginWarning != nil) ? ", Claude 로그인 만료 임박" : ""
    if let pct = s.observedFresh(now: now) {
        return "Trunkline — 활성 \(active), 잔여 \(Int((100 - pct).rounded()))%\(claudeSuffix)"
    }
    return "Trunkline — 활성 \(active), 사용량 미상\(claudeSuffix)"
}
