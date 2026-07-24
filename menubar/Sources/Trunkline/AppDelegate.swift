import AppKit
import ServiceManagement
import TrunklineKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let statePath = NSHomeDirectory() + "/.trunkline/state.json"
    private let stateDir = NSHomeDirectory() + "/.trunkline"
    private var statusItem: NSStatusItem!
    private let watcher = StateWatcher()
    private let cli = CLIRunner()
    private var state: TrunklineState?
    private var usageReport: UsageReport?
    private var wakeGraceUntil: Double = 0
    private var pythonWarning: String?
    private var lastUsageAttempt: Double?
    private var usageInFlight = false

    func applicationDidFinishLaunching(_ n: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = MenuBarGlyph.make()
        statusItem.button?.imagePosition = .imageLeading
        try? SMAppService.mainApp.register()
        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(didWake), name: NSWorkspace.didWakeNotification, object: nil)
        if (try? CLIExecutableResolver.resolve()) == nil {
            pythonWarning = "Trunkline CLI 없음 — pipx install trunkline 필요"
        }
        watcher.onChange = { [weak self] in DispatchQueue.main.async { self?.reload() } }
        watcher.start(directory: stateDir)
        reload()
    }

    @objc private func didWake() {
        wakeGraceUntil = Date().timeIntervalSince1970 + 20
    }

    private func reload() {
        if let data = FileManager.default.contents(atPath: statePath),
           let s = TrunklineState.load(from: data) {
            state = s
        }   // 파싱 실패 시 이전 모델 유지 (설계 §4.5)
        render()
    }

    private func render() {
        let now = Date().timeIntervalSince1970
        statusItem.button?.title = statusTitle(state: state, now: now, wakeGraceUntil: wakeGraceUntil)
        statusItem.button?.setAccessibilityLabel(
            statusAccessibilityLabel(state: state, now: now, wakeGraceUntil: wakeGraceUntil))
        let specs = buildMenuSpec(state: state, usage: usageReport?.rows, now: now,
                                  wakeGraceUntil: wakeGraceUntil, pythonWarning: pythonWarning,
                                  claudeDetail: usageReport?.claude)
        statusItem.menu = makeMenu(specs)
    }

    private func makeMenu(_ specs: [MenuItemSpec]) -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        menu.delegate = self
        for spec in specs { menu.addItem(makeItem(spec)) }
        return menu
    }

    private func makeItem(_ spec: MenuItemSpec) -> NSMenuItem {
        if spec.isSeparator { return .separator() }
        if let gauge = spec.gauge {
            let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
            item.isEnabled = false
            item.view = GaugeRowView(spec: gauge)
            return item
        }
        let item = NSMenuItem(title: spec.title, action: nil, keyEquivalent: "")
        item.isEnabled = spec.enabled
        if let runs = spec.rightRuns {
            item.attributedTitle = Self.attributedTitle(title: spec.title, rightRuns: runs)
        }
        if let sub = spec.submenu {
            let m = NSMenu(); m.autoenablesItems = false
            for s in sub { m.addItem(makeItem(s)) }
            item.submenu = m
        }
        if spec.isQuit {
            item.action = #selector(NSApplication.terminate(_:)); item.isEnabled = true
        } else if spec.isUsageReload {
            item.action = #selector(reloadUsage); item.target = self; item.isEnabled = true
        } else if let args = spec.action {
            item.action = #selector(runAction(_:)); item.target = self
            item.representedObject = args
        }
        return item
    }

    /// title + 우측 탭 정렬된 rightRuns 조립 — 탭 위치는 GaugeRowView.rowSize/rowInset 유래 공유
    /// 상수에서 파생(게이지 행 우측 정렬선과 근사 일치 — NSMenuItem 텍스트 인셋 특성상 완전 일치는 불가).
    /// 각 run을 " · " 구분자와 자기 색(color(for:))으로 개별 append — 대표 스타일 평탄화 없이 시맨틱 색 보존.
    /// 폭 초과 시 byTruncatingTail.
    private static func attributedTitle(title: String, rightRuns: [StyledRun]) -> NSAttributedString {
        let width = GaugeRowView.rowSize.width - GaugeRowView.rowInset
        let margin: CGFloat = 16
        let paragraph = NSMutableParagraphStyle()
        paragraph.tabStops = [NSTextTab(textAlignment: .right, location: width - margin, options: [:])]
        paragraph.lineBreakMode = .byTruncatingTail

        let result = NSMutableAttributedString(
            string: title,
            attributes: [.paragraphStyle: paragraph, .font: NSFont.menuFont(ofSize: 0)])
        for (index, run) in rightRuns.enumerated() where !run.text.isEmpty {
            let prefix = index == 0 ? "\t" : " · "
            result.append(NSAttributedString(string: "\(prefix)\(run.text)", attributes: [
                .paragraphStyle: paragraph,
                .font: NSFont.menuFont(ofSize: 0),
                .foregroundColor: color(for: run.style),
            ]))
        }
        return result
    }

    private static func color(for style: RunStyle) -> NSColor {
        switch style {
        case .normal: return .labelColor
        case .dim: return .secondaryLabelColor
        case .warn: return .systemOrange
        case .danger: return .systemRed
        }
    }

    /// usage --json 조회 공통 경로 — 성공 시에만 usageReport 대입(실패 시 이전 보고 유지),
    /// in-flight 플래그·마지막 시도 시각 갱신 후 completion에서 호출부별 후속 처리(render/updateOpenMenu) 분기.
    private func fetchUsage(then completion: @escaping () -> Void) {
        lastUsageAttempt = Date().timeIntervalSince1970
        usageInFlight = true
        cli.run(["usage", "--json"], lane: .query, timeout: 40) { [weak self] r in
            DispatchQueue.main.async {
                guard let self else { return }
                self.usageInFlight = false
                if let report = UsageReport.decode(Data(r.stdout.utf8)) { self.usageReport = report }
                completion()
            }
        }
    }

    @objc private func reloadUsage() {
        guard !usageInFlight else { return }
        fetchUsage { [weak self] in self?.render() }
    }

    // MARK: - NSMenuDelegate

    func menuWillOpen(_ menu: NSMenu) {
        let now = Date().timeIntervalSince1970
        guard shouldTriggerMenuReload(now: now, lastAttempt: lastUsageAttempt, inFlight: usageInFlight)
        else { return }
        fetchUsage { [weak self] in self?.updateOpenMenu(menu) }
    }

    /// 열려 있는 메뉴 인스턴스를 in-place 갱신(removeAllItems+재구성) + statusItem.menu 동기화.
    private func updateOpenMenu(_ menu: NSMenu) {
        let now = Date().timeIntervalSince1970
        let specs = buildMenuSpec(state: state, usage: usageReport?.rows, now: now,
                                  wakeGraceUntil: wakeGraceUntil, pythonWarning: pythonWarning,
                                  claudeDetail: usageReport?.claude)
        menu.removeAllItems()
        for spec in specs { menu.addItem(makeItem(spec)) }
        statusItem.menu = menu
        statusItem.button?.title = statusTitle(state: state, now: now, wakeGraceUntil: wakeGraceUntil)
        statusItem.button?.setAccessibilityLabel(
            statusAccessibilityLabel(state: state, now: now, wakeGraceUntil: wakeGraceUntil))
    }

    @objc private func runAction(_ sender: NSMenuItem) {
        guard let args = sender.representedObject as? [String] else { return }
        cli.run(args, lane: .action, timeout: 30) { [weak self] r in
            DispatchQueue.main.async {
                if r.rc != 0 {
                    let alert = NSAlert()
                    alert.messageText = "trunkline \(args.joined(separator: " ")) 실패"
                    alert.informativeText = r.stderr.split(separator: "\n").first.map(String.init) ?? "rc=\(r.rc)"
                    alert.runModal()
                }
                self?.reload()
            }
        }
    }
}
