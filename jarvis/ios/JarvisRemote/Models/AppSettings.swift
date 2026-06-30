//
//  AppSettings.swift
//  JarvisRemote
//
//  User-editable connection + behavior settings, persisted in UserDefaults.
//  These mirror the REMOTE_* values in the Mac's Jarvis .env.
//

import Foundation
import Combine

final class AppSettings: ObservableObject {
    /// The Mac's Tailscale IP (`tailscale ip -4` on the Mac), e.g. 100.x.y.z.
    @Published var host: String {
        didSet { defaults.set(host, forKey: Keys.host) }
    }
    @Published var port: Int {
        didSet { defaults.set(port, forKey: Keys.port) }
    }
    @Published var username: String {
        didSet { defaults.set(username, forKey: Keys.username) }
    }
    @Published var password: String {
        didSet { defaults.set(password, forKey: Keys.password) }
    }
    /// Topic Jarvis listens on (REMOTE_CMD_TOPIC).
    @Published var commandTopic: String {
        didSet { defaults.set(commandTopic, forKey: Keys.commandTopic) }
    }
    /// Topic Jarvis publishes replies to (REMOTE_REPLY_TOPIC).
    @Published var replyTopic: String {
        didSet { defaults.set(replyTopic, forKey: Keys.replyTopic) }
    }
    /// After dictation finishes, send automatically (vs. let you edit first).
    @Published var autoSendAfterSpeech: Bool {
        didSet { defaults.set(autoSendAfterSpeech, forKey: Keys.autoSend) }
    }
    /// Also read Jarvis's replies aloud on the phone (AVSpeechSynthesizer).
    @Published var speakRepliesOnPhone: Bool {
        didSet { defaults.set(speakRepliesOnPhone, forKey: Keys.speakReplies) }
    }

    private let defaults = UserDefaults.standard

    private enum Keys {
        static let host = "host"
        static let port = "port"
        static let username = "username"
        static let password = "password"
        static let commandTopic = "commandTopic"
        static let replyTopic = "replyTopic"
        static let autoSend = "autoSendAfterSpeech"
        static let speakReplies = "speakRepliesOnPhone"
    }

    init() {
        host = defaults.string(forKey: Keys.host) ?? ""
        let storedPort = defaults.integer(forKey: Keys.port)
        port = storedPort == 0 ? 1883 : storedPort
        username = defaults.string(forKey: Keys.username) ?? "jarvis"
        password = defaults.string(forKey: Keys.password) ?? ""
        commandTopic = defaults.string(forKey: Keys.commandTopic) ?? "jarvis/command"
        replyTopic = defaults.string(forKey: Keys.replyTopic) ?? "jarvis/reply"
        autoSendAfterSpeech = defaults.object(forKey: Keys.autoSend) as? Bool ?? true
        speakRepliesOnPhone = defaults.object(forKey: Keys.speakReplies) as? Bool ?? false
    }

    /// True once enough is filled in to attempt a connection.
    var isConfigured: Bool {
        !host.isEmpty && port > 0 && !commandTopic.isEmpty && !replyTopic.isEmpty
    }
}
