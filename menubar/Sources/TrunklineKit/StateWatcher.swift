import Foundation

public final class StateWatcher {
    private var fd: CInt = -1
    private var source: DispatchSourceFileSystemObject?
    private var timer: DispatchSourceTimer?
    public var onChange: (@Sendable () -> Void)?

    public init() {}

    public func start(directory: String, fallbackInterval: TimeInterval = 3.0) {
        stop()
        fd = open(directory, O_EVTONLY)
        if fd >= 0 {
            let s = DispatchSource.makeFileSystemObjectSource(
                fileDescriptor: fd, eventMask: [.write], queue: .main)
            s.setEventHandler { [weak self] in self?.onChange?() }
            s.resume()
            source = s
        }
        let t = DispatchSource.makeTimerSource(queue: .main)
        t.schedule(deadline: .now() + fallbackInterval, repeating: fallbackInterval)
        t.setEventHandler { [weak self] in self?.onChange?() }
        t.resume()
        timer = t
    }

    public func stop() {
        source?.cancel(); source = nil
        timer?.cancel(); timer = nil
        if fd >= 0 { close(fd); fd = -1 }
    }
}
