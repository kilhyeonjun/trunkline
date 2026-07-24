// MIT License
//
// Copyright (c) 2026 Peter Steinberger
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
//
// Ported from CodexBar's UsagePace.swift (Sources/CodexBarCore/UsagePace.swift) —
// formula, clamp order and comparison operators kept as-is; public surface and
// Korean formatting are new for trunkline.

import Foundation

public enum PaceBucket: Equatable { case reserve, onTrack, over }

public struct PaceResult: Equatable {
    public let expectedPercent: Double?
    public let bucket: PaceBucket?
    public let statusWord: String?
    public let etaText: String?
    public let resetText: String?
    public let staleOverride: String?
}

/// 원본 CodexBar UsagePace 세분 stage(2/6/12 경계) — bucket으로 롤업되어 공개된다.
private enum PaceStage {
    case onTrack, slightlyAhead, ahead, farAhead, slightlyBehind, behind, farBehind

    static func stage(for delta: Double) -> PaceStage {
        let absDelta = abs(delta)
        if absDelta <= 2 { return .onTrack }
        if absDelta <= 6 { return delta >= 0 ? .slightlyAhead : .slightlyBehind }
        if absDelta <= 12 { return delta >= 0 ? .ahead : .behind }
        return delta >= 0 ? .farAhead : .farBehind
    }

    var bucket: PaceBucket {
        switch self {
        case .onTrack: return .onTrack
        case .slightlyAhead, .ahead, .farAhead: return .over
        case .slightlyBehind, .behind, .farBehind: return .reserve
        }
    }
}

private func clamp(_ value: Double, lower: Double, upper: Double) -> Double {
    min(upper, max(lower, value))
}

/// pace 마커·상태어·ETA 계산. 공식·clamp 순서·비교 연산자는 원본(UsagePace.swift) 그대로.
///
/// - Parameters:
///   - now: pace 수학 기준 시각(codex=렌더 시각, claude=fetched_at — 호출자 결정).
///   - wallClock: 리셋 경과 판정 전용 벽시계 시각.
public func computePace(
    usedPercent: Double,
    resetsAt: Double?,
    windowMinutes: Int?,
    now: Double,
    wallClock: Double,
    dataAgeSeconds: Double?
) -> PaceResult {
    let empty = PaceResult(expectedPercent: nil, bucket: nil, statusWord: nil,
                            etaText: nil, resetText: nil, staleOverride: nil)

    guard let resetsAt else { return empty }

    if resetsAt < wallClock {
        let dataAge = dataAgeSeconds ?? 0
        let windowDuration = windowMinutes.map { Double($0) * 60 }
        let override: String
        if let windowDuration, dataAge > windowDuration {
            override = relativeText(seconds: dataAge) + " 전 데이터 — 사용 시 자동 갱신"
        } else {
            override = "리셋 지남 — 갱신 필요"
        }
        return PaceResult(expectedPercent: nil, bucket: nil, statusWord: nil, etaText: nil,
                           resetText: nil, staleOverride: override)
    }

    let resetText = relativeText(seconds: resetsAt - wallClock) + " 후 리셋"

    guard let windowMinutes, windowMinutes > 0 else {
        return PaceResult(expectedPercent: nil, bucket: nil, statusWord: nil, etaText: nil,
                           resetText: resetText, staleOverride: nil)
    }

    let duration = Double(windowMinutes) * 60
    let timeUntilReset = resetsAt - now
    guard timeUntilReset > 0, timeUntilReset <= duration else {
        return PaceResult(expectedPercent: nil, bucket: nil, statusWord: nil, etaText: nil,
                           resetText: resetText, staleOverride: nil)
    }

    let elapsed = clamp(duration - timeUntilReset, lower: 0, upper: duration)
    let expected = clamp((elapsed / duration) * 100, lower: 0, upper: 100)
    let actual = clamp(usedPercent, lower: 0, upper: 100)
    if elapsed == 0, actual > 0 {
        return PaceResult(expectedPercent: nil, bucket: nil, statusWord: nil, etaText: nil,
                           resetText: resetText, staleOverride: nil)
    }

    let remaining = 100 - actual
    let dataAge = dataAgeSeconds ?? 0
    guard expected >= 3.0, remaining > 0, dataAge <= duration else {
        return PaceResult(expectedPercent: nil, bucket: nil, statusWord: nil, etaText: nil,
                           resetText: resetText, staleOverride: nil)
    }

    let delta = actual - expected
    let stage = PaceStage.stage(for: delta)
    let bucket = stage.bucket

    var etaText: String?
    if elapsed > 0, actual > 0 {
        let rate = actual / elapsed
        if rate > 0 {
            let candidate = remaining / rate
            if candidate >= timeUntilReset {
                etaText = "리셋까지 유지"
            } else {
                etaText = relativeText(seconds: candidate) + " 후 소진"
            }
        }
    } else if elapsed > 0, actual == 0 {
        etaText = "리셋까지 유지"
    }

    let statusWord: String
    switch bucket {
    case .onTrack: statusWord = "정상 속도"
    case .reserve: statusWord = "\(Int(abs(delta).rounded()))% 여유"
    case .over: statusWord = "\(Int(abs(delta).rounded()))% 초과"
    }

    return PaceResult(expectedPercent: expected, bucket: bucket, statusWord: statusWord,
                       etaText: etaText, resetText: resetText, staleOverride: nil)
}

/// "58% 남음" — usedPercent 반올림 잔여율(하한 0 클램프 — 100% 초과 보고 시 음수 방지).
public func remainText(usedPercent: Double) -> String {
    "\(Int(max(0, 100 - usedPercent).rounded()))% 남음"
}

/// 상위 2단위만, 0단위 생략. 1분 미만은 "잠시"(호출부가 " 후 리셋"/" 후 소진"을 붙여 합성).
public func relativeText(seconds: Double) -> String {
    let total = Int(seconds.rounded())
    guard total >= 60 else { return "잠시" }

    let days = total / 86400
    let hours = (total % 86400) / 3600
    let minutes = (total % 3600) / 60

    if days > 0 {
        return hours > 0 ? "\(days)일 \(hours)시간" : "\(days)일"
    }
    if hours > 0 {
        return minutes > 0 ? "\(hours)시간 \(minutes)분" : "\(hours)시간"
    }
    return "\(minutes)분"
}
