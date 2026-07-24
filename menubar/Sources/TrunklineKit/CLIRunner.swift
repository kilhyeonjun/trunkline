import Foundation

public enum CLILane { case action, query }
public enum CLIError: Error { case disallowed(String) }

public struct CLIResult: Equatable, Sendable {
    public let rc: Int32
    public let stdout: String
    public let stderr: String
}

public enum CLIResolutionError: Error, CustomStringConvertible {
    case notInstalled

    public var description: String {
        "Trunkline CLI not found. Install it with: pipx install trunkline"
    }
}

public enum CLIExecutableResolver {
    public static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        pathExists: (String) -> Bool = FileManager.default.isExecutableFile(atPath:)
    ) throws -> URL {
        var candidates: [String] = []
        if let explicit = environment["TRUNKLINE_CLI"], !explicit.isEmpty {
            candidates.append(explicit)
        }
        if let home = environment["HOME"], !home.isEmpty {
            candidates += [
                "\(home)/.local/bin/trunkline",
                "\(home)/Library/Python/3.12/bin/trunkline",
                "\(home)/Library/Python/3.11/bin/trunkline",
            ]
        }
        candidates += (environment["PATH"] ?? "")
            .split(separator: ":")
            .map { "\($0)/trunkline" }
        guard let match = candidates.first(where: pathExists) else {
            throw CLIResolutionError.notInstalled
        }
        return URL(fileURLWithPath: match)
    }
}

public final class CLIRunner: @unchecked Sendable {
    public static let allowed: Set<String> = ["status", "usage", "switch", "pin", "auto", "lock"]

    let actionQueue = DispatchQueue(label: "trunkline.cli.action")
    let queryQueue = DispatchQueue(label: "trunkline.cli.query")
    private let executableURL: URL?
    public var executableOverride: String?   // 테스트 전용

    public init(executableURL: URL? = nil) {
        self.executableURL = executableURL
    }

    public func buildProcess(_ args: [String]) throws -> Process {
        guard let cmd = args.first, Self.allowed.contains(cmd) else {
            throw CLIError.disallowed(args.first ?? "")
        }
        let p = Process()
        if let ov = executableOverride {
            p.executableURL = URL(fileURLWithPath: ov)
            p.arguments = Array(args.dropFirst())   // 테스트 스크립트가 인자 소비
        } else {
            p.executableURL = try executableURL ?? CLIExecutableResolver.resolve()
            p.arguments = args
        }
        var env = ProcessInfo.processInfo.environment
        env.removeValue(forKey: "PYTHONPATH")
        p.environment = env
        return p
    }

    public func run(_ args: [String], lane: CLILane, timeout: TimeInterval = 30,
                    completion: @escaping @Sendable (CLIResult) -> Void) {
        let queue = lane == .action ? actionQueue : queryQueue
        queue.async {
            do {
                let p = try self.buildProcess(args)
                let out = Pipe(); let err = Pipe()
                p.standardOutput = out; p.standardError = err
                try p.run()
                let killer = DispatchWorkItem { if p.isRunning { p.terminate() } }
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
                p.waitUntilExit()
                killer.cancel()
                let o = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                let e = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                completion(CLIResult(rc: p.terminationStatus, stdout: o, stderr: e))
            } catch {
                completion(CLIResult(rc: 127, stdout: "", stderr: "\(error)"))
            }
        }
    }
}
