//
//  MQTTService.swift
//  JarvisRemote
//
//  Thin wrapper around CocoaMQTT. Connects to the Mac's mosquitto broker
//  (over Tailscale), publishes commands to the command topic, and surfaces
//  replies from the reply topic.
//
//  Built against CocoaMQTT 2.1.x (SwiftPM: https://github.com/emqx/CocoaMQTT).
//  If your CocoaMQTT version's delegate protocol differs, Xcode will flag the
//  mismatched methods below — adjust the signatures to match that version.
//

import Foundation
import Combine
import CocoaMQTT

/// Decoded reply coming back from Jarvis.
struct JarvisReply: Codable {
    let id: String
    let text: String
    let ts: Int?
}

/// Command we send up to Jarvis.
private struct JarvisCommand: Codable {
    let id: String
    let text: String
    let ts: Int
    let src: String
}

final class MQTTService: NSObject, ObservableObject {
    enum Status: Equatable {
        case disconnected
        case connecting
        case connected
        case error(String)
    }

    @Published private(set) var status: Status = .disconnected

    /// Called on the main thread for each reply received (id, text).
    var onReply: ((String, String) -> Void)?

    private var mqtt: CocoaMQTT?
    private var replyTopic = "jarvis/reply"

    var isConnected: Bool { status == .connected }

    // MARK: - Lifecycle

    /// Open a connection using the given settings. Safe to call repeatedly;
    /// it tears down any existing client first.
    func connect(using settings: AppSettings) {
        disconnect()

        let clientID = "jarvis-ios-" + UUID().uuidString.prefix(8)
        let client = CocoaMQTT(clientID: String(clientID),
                               host: settings.host,
                               port: UInt16(settings.port))
        if !settings.username.isEmpty {
            client.username = settings.username
            client.password = settings.password
        }
        client.keepAlive = 60
        client.autoReconnect = true
        client.cleanSession = true
        client.delegate = self

        self.replyTopic = settings.replyTopic
        self.mqtt = client

        setStatus(.connecting)
        _ = client.connect()
    }

    func disconnect() {
        mqtt?.disconnect()
        mqtt = nil
        setStatus(.disconnected)
    }

    // MARK: - Publish

    /// Send a command to Jarvis. Returns the message id so the caller can
    /// correlate the eventual reply.
    @discardableResult
    func send(_ text: String) -> String {
        let id = UUID().uuidString
        guard let mqtt = mqtt, isConnected else { return id }
        let command = JarvisCommand(id: id,
                                    text: text,
                                    ts: Int(Date().timeIntervalSince1970),
                                    src: "ios")
        if let data = try? JSONEncoder().encode(command),
           let json = String(data: data, encoding: .utf8) {
            mqtt.publish(currentCommandTopic, withString: json, qos: .qos1)
        }
        return id
    }

    /// Set just before each send so the publish uses the live topic.
    var currentCommandTopic = "jarvis/command"

    // MARK: - Helpers

    private func setStatus(_ new: Status) {
        DispatchQueue.main.async { self.status = new }
    }

    private func handleIncoming(topic: String, payload: String) {
        guard topic == replyTopic else { return }
        guard let data = payload.data(using: .utf8) else { return }
        // Prefer structured {id,text,ts}; fall back to a bare string.
        if let reply = try? JSONDecoder().decode(JarvisReply.self, from: data) {
            DispatchQueue.main.async { self.onReply?(reply.id, reply.text) }
        } else {
            DispatchQueue.main.async { self.onReply?("", payload) }
        }
    }
}

// MARK: - CocoaMQTTDelegate

extension MQTTService: CocoaMQTTDelegate {
    func mqtt(_ mqtt: CocoaMQTT, didConnectAck ack: CocoaMQTTConnAck) {
        if ack == .accept {
            setStatus(.connected)
            mqtt.subscribe(replyTopic, qos: .qos1)
        } else {
            setStatus(.error("Broker rejected connection (\(ack))."))
        }
    }

    func mqtt(_ mqtt: CocoaMQTT, didReceiveMessage message: CocoaMQTTMessage, id: UInt16) {
        handleIncoming(topic: message.topic, payload: message.string ?? "")
    }

    func mqttDidDisconnect(_ mqtt: CocoaMQTT, withError err: Error?) {
        if let err = err {
            setStatus(.error(err.localizedDescription))
        } else {
            setStatus(.disconnected)
        }
    }

    // Remaining delegate methods are required by the protocol but unused here.
    func mqtt(_ mqtt: CocoaMQTT, didPublishMessage message: CocoaMQTTMessage, id: UInt16) {}
    func mqtt(_ mqtt: CocoaMQTT, didPublishAck id: UInt16) {}
    func mqtt(_ mqtt: CocoaMQTT, didSubscribeTopics success: NSDictionary, failed: [String]) {}
    func mqtt(_ mqtt: CocoaMQTT, didUnsubscribeTopics topics: [String]) {}
    func mqttDidPing(_ mqtt: CocoaMQTT) {}
    func mqttDidReceivePong(_ mqtt: CocoaMQTT) {}
}
