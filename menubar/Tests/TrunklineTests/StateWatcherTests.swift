import XCTest
@testable import TrunklineKit

final class StateWatcherTests: XCTestCase {
    func testAtomicRenameTriggersOnChange() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("StateWatcherTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let watcher = StateWatcher()
        let exp = expectation(description: "onChange fired")
        exp.assertForOverFulfill = false
        watcher.onChange = { exp.fulfill() }
        watcher.start(directory: dir.path, fallbackInterval: 60)

        let target = dir.appendingPathComponent("state.json")
        let tmp = dir.appendingPathComponent(".state.json.tmp")
        try "{}".write(to: tmp, atomically: false, encoding: .utf8)
        try FileManager.default.moveItem(at: tmp, to: target)

        wait(for: [exp], timeout: 2.0)
        watcher.stop()
    }

    func testNoOnChangeAfterStop() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("StateWatcherTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let watcher = StateWatcher()
        let noExp = expectation(description: "should not fire")
        noExp.isInverted = true
        watcher.onChange = { noExp.fulfill() }
        watcher.start(directory: dir.path, fallbackInterval: 60)
        watcher.stop()

        let target = dir.appendingPathComponent("state.json")
        let tmp = dir.appendingPathComponent(".state.json.tmp")
        try "{}".write(to: tmp, atomically: false, encoding: .utf8)
        try FileManager.default.moveItem(at: tmp, to: target)

        // stopped watcher must not react within a generous window
        wait(for: [noExp], timeout: 1.0)
    }
}
