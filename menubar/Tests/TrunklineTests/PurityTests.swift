import XCTest

final class PurityTests: XCTestCase {
    static let banned = ["auth.json", "accounts.json", ".codex", "refresh", "oauth",
                         "URLSession", "NSURLConnection", "NWConnection", "CFNetwork",
                         "Keychain", "SecItem", "curl", "socket("]

    private func sourceFiles() throws -> [(String, String)] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources")
        let files = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)!
            .compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" }
        XCTAssertFalse(files.isEmpty)
        return try files.map { ($0.lastPathComponent, try String(contentsOf: $0, encoding: .utf8)) }
    }

    func testNoBannedSymbols() throws {
        for (name, text) in try sourceFiles() {
            for b in Self.banned {
                XCTAssertFalse(text.contains(b), "\(name) contains banned string: \(b)")
            }
        }
    }

    func testProcessOnlyInCLIRunner() throws {
        for (name, text) in try sourceFiles() where name != "CLIRunner.swift" {
            XCTAssertFalse(text.contains("Process("), "\(name) spawns Process")
        }
    }
}
