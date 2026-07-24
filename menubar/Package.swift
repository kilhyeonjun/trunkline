// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Trunkline",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "TrunklineKit"),
        .executableTarget(name: "Trunkline", dependencies: ["TrunklineKit"]),
        .testTarget(name: "TrunklineTests", dependencies: ["TrunklineKit"]),
    ],
    swiftLanguageModes: [.v5]   // strict concurrency와의 소모전 회피 (설계 §7 의도 유지)
)
