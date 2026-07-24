import XCTest
@testable import TrunklineKit

final class ResultBox: @unchecked Sendable {
    var result: CLIResult?
}

final class CLIRunnerTests: XCTestCase {
    func testResolverPrefersExplicitEnvironmentPath() throws {
        let url = try CLIExecutableResolver.resolve(
            environment: ["TRUNKLINE_CLI": "/opt/trunkline/bin/trunkline"],
            pathExists: { $0 == "/opt/trunkline/bin/trunkline" }
        )
        XCTAssertEqual(url.path, "/opt/trunkline/bin/trunkline")
    }

    func testResolverSearchesStandardUserPaths() throws {
        let url = try CLIExecutableResolver.resolve(
            environment: ["HOME": "/tmp/tester", "PATH": "/usr/bin:/bin"],
            pathExists: { $0 == "/tmp/tester/.local/bin/trunkline" }
        )
        XCTAssertEqual(url.path, "/tmp/tester/.local/bin/trunkline")
    }

    func testResolverReportsInstallHintWhenMissing() {
        XCTAssertThrowsError(try CLIExecutableResolver.resolve(
            environment: ["HOME": "/tmp/tester", "PATH": "/usr/bin"],
            pathExists: { _ in false }
        )) { error in
            XCTAssertTrue(String(describing: error).contains("pipx install"))
        }
    }

    func testBuildProcessRunsResolvedConsoleScriptDirectly() throws {
        let runner = CLIRunner(executableURL: URL(fileURLWithPath: "/opt/bin/trunkline"))
        let process = try runner.buildProcess(["pin", "personal"])
        XCTAssertEqual(process.executableURL?.path, "/opt/bin/trunkline")
        XCTAssertEqual(process.arguments, ["pin", "personal"])
        XCTAssertNil(process.environment?["PYTHONPATH"])
    }

    func testAllowlistRejectsDisallowedCommands() {
        let runner = CLIRunner()
        for bad in ["adopt", "init", "login", "cutover", "daemon"] {
            XCTAssertThrowsError(try runner.buildProcess([bad, "x"])) { error in
                guard case CLIError.disallowed(let cmd) = error else {
                    return XCTFail("expected CLIError.disallowed, got \(error)")
                }
                XCTAssertEqual(cmd, bad)
            }
        }
    }

    func testAllowlistAcceptsAllowedCommands() throws {
        let runner = CLIRunner(executableURL: URL(fileURLWithPath: "/usr/bin/true"))
        for good in ["status", "usage", "switch", "pin", "auto", "lock"] {
            XCTAssertNoThrow(try runner.buildProcess([good]))
        }
    }

    /// 같은 lane(action)에 2개 작업을 넣으면 순차 실행되어야 함 — 공유 파일에 순번이 기록된 순서로 검증.
    func testSameLaneSerializesExecution() throws {
        let tmpDir = FileManager.default.temporaryDirectory
        let logPath = tmpDir.appendingPathComponent("cli-order-\(UUID().uuidString).txt").path
        FileManager.default.createFile(atPath: logPath, contents: nil)

        let scriptPath = tmpDir.appendingPathComponent("cli-script-\(UUID().uuidString).sh").path
        let script = """
        #!/bin/sh
        sleep 0.2
        echo "$1" >> "\(logPath)"
        """
        try script.write(toFile: scriptPath, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: scriptPath)

        let runner = CLIRunner()
        runner.executableOverride = scriptPath

        let exp1 = expectation(description: "first")
        let exp2 = expectation(description: "second")

        runner.run(["status", "first"], lane: .action) { _ in exp1.fulfill() }
        runner.run(["status", "second"], lane: .action) { _ in exp2.fulfill() }

        wait(for: [exp1, exp2], timeout: 3)

        let recorded = try String(contentsOfFile: logPath, encoding: .utf8)
            .split(separator: "\n").map(String.init)
        XCTAssertEqual(recorded, ["first", "second"])
    }

    /// executableOverride=/bin/sleep, timeout 0.5s → rc != 0, 1s 내 완료.
    func testTimeoutKillsLongRunningProcess() {
        let runner = CLIRunner()
        runner.executableOverride = "/bin/sleep"

        let exp = expectation(description: "timeout completion")
        let box = ResultBox()
        let start = Date()
        runner.run(["status", "5"], lane: .query, timeout: 0.5) { r in
            box.result = r
            exp.fulfill()
        }
        wait(for: [exp], timeout: 2)
        let elapsed = Date().timeIntervalSince(start)

        XCTAssertLessThan(elapsed, 1.0)
        XCTAssertNotEqual(box.result?.rc, 0)
    }
}
