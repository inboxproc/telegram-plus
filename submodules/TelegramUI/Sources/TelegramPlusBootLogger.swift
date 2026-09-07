//
// TelegramPlusBootLogger.swift
// Mininal startup instrumentation for Telegram Plus (black-screen diagnostic).
//
// Purpose: record the actual startup chain of Telegram Plus with a persistent,
// device-readable log so we can pinpoint the FIRST FAILURE that leaves a black
// screen after launch. This is a DIAGNOSTIC-ONLY logger: it never alters
// production behavior, never adds artificial timeouts, never touches control
// flow. It merely records landmarks as the app boots.
//
// Format of each record (matches the TZ spec):
//   [TP-BOOT] HH:mm:ss.SSS | <stage> | <event> | <details>
//
// Channel: writes through SGLogger (persistent file inside the App Group
// container) AND NSLog (visible in the device console / streamed via
// `log stream`). The file copy survives in Files app → Telegram Plus →
// /logs/app-logs-sg/<date>.log, so it can be retrieved even without a Mac.
//

import Foundation
import SGLogging
import UIKit

public final class TelegramPlusBootLogger {
    public static let shared = TelegramPlusBootLogger()

    private let dateFormatter: DateFormatter
    private let pid: Int
    private let ident: String
    private let enableFile: Bool
    private let enableConsole: Bool
    private let enableNSLog: Bool

    /// Lightweight struct describing one startup landmark.
    public struct Entry {
        public let stage: String
        public let event: String
        public let details: String
    }

    private init() {
        self.dateFormatter = DateFormatter()
        self.dateFormatter.dateFormat = "HH:mm:ss.SSS"
        self.pid = Int(getpid())
        self.ident = "TP-BOOT"
        self.enableFile = true
        self.enableConsole = true
        self.enableNSLog = true
    }

    /// Emit one startup landmark.
    /// - stage: short monospace stage tag, e.g. "001", "002" (sequence) or a
    ///   named stage like "accountContext".
    /// - event: one of START / SUCCESS / ERROR / WAITING / COMPLETE / STATE.
    /// - details: free-form facts, never sensitive account/personal data.
    public func log(_ stage: String, _ event: String, _ details: String = "") {
        let ts = self.dateFormatter.string(from: Date())
        let line = "[\(self.ident)] \(ts) | \(stage) | \(event) | \(details)"

        if self.enableConsole {
            // SGLogger writes to the persistent file AND (if logToConsole)
            // to stdout. It routes to the App Group container path.
            SGLogger.shared.log(self.ident, line)
        }

        if self.enableNSLog {
            // Always duplicate to NSLog so the record is visible in
            // device logs even before the file-based logger is initialised.
            NSLog("%@", line)
        }
    }

    // Convenience helpers to keep call sites terse.
    public func start(_ stage: String, _ details: String = "") {
        self.log(stage, "START", details)
    }
    public func success(_ stage: String, _ details: String = "") {
        self.log(stage, "SUCCESS", details)
    }
    public func error(_ stage: String, _ details: String = "") {
        self.log(stage, "ERROR", details)
    }
    public func waiting(_ stage: String, _ details: String = "") {
        self.log(stage, "WAITING", details)
    }
    public func complete(_ stage: String, _ details: String = "") {
        self.log(stage, "COMPLETE", details)
    }
    public func state(_ stage: String, _ details: String = "") {
        self.log(stage, "STATE", details)
    }

    /// Dump a compact snapshot of a UIWindow's runtime state.
    public func windowState(_ stage: String, _ window: UIWindow?) {
        guard let window = window else {
            self.log(stage, "WINDOW_STATE", "window=nil")
            return
        }
        var sceneState: String = "n/a"
        if let scene = window.windowScene {
            switch scene.activationState {
            case .active: sceneState = "active"
            case .inactive: sceneState = "inactive"
            case .background: sceneState = "background"
            case .foregroundActive: sceneState = "foregroundActive"
            case .foregroundInactive: sceneState = "foregroundInactive"
            case .unattached: sceneState = "unattached"
            @unknown default: sceneState = "unknown"
            }
        }
        let rootVC = window.rootViewController.map { NSStringFromClass(type(of: $0)) } ?? "nil"
        self.state(stage, "WINDOW kkey=\\(window.isKeyWindow) hidden=\\(window.isHidden) frame=\\(window.frame) bounds=\\(window.bounds) rootVC=\\(rootVC) scene=\\(sceneState)")
    }
}
