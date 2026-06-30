//
//  ChatViewModel.swift
//  JarvisRemote
//
//  Glues the chat UI to the MQTT service and the speech recognizer:
//   - sending text (typed or dictated) publishes a command to Jarvis
//   - replies coming back over MQTT append assistant bubbles
//   - dictation streams live into the draft, then optionally auto-sends
//

import Foundation
import Combine
import AVFoundation

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var draft: String = ""

    private var settings: AppSettings?
    private var mqtt: MQTTService?
    private var speech: SpeechRecognizer?

    private var cancellables = Set<AnyCancellable>()
    private let synthesizer = AVSpeechSynthesizer()
    private var configured = false

    /// Wire up the environment objects. Call once from ChatView.onAppear.
    func configure(settings: AppSettings, mqtt: MQTTService, speech: SpeechRecognizer) {
        guard !configured else { return }
        configured = true
        self.settings = settings
        self.mqtt = mqtt
        self.speech = speech

        // Incoming replies -> assistant bubbles (+ optional phone TTS).
        mqtt.onReply = { [weak self] _, text in
            guard let self = self, !text.isEmpty else { return }
            self.messages.append(ChatMessage(role: .assistant, text: text))
            if settings.speakRepliesOnPhone {
                self.speakOnPhone(text)
            }
        }

        // Live dictation streams into the draft field.
        speech.$transcript
            .receive(on: RunLoop.main)
            .sink { [weak self] text in
                guard let self = self, self.speech?.isRecording == true else { return }
                self.draft = text
            }
            .store(in: &cancellables)
    }

    // MARK: - Sending

    var isConnected: Bool { mqtt?.isConnected ?? false }

    func send(_ raw: String? = nil) {
        let text = (raw ?? draft).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let mqtt = mqtt, let settings = settings else { return }
        messages.append(ChatMessage(role: .user, text: text))
        mqtt.currentCommandTopic = settings.commandTopic
        mqtt.send(text)
        draft = ""
    }

    // MARK: - Dictation

    var isRecording: Bool { speech?.isRecording ?? false }

    func toggleDictation() {
        guard let speech = speech else { return }
        if speech.isRecording {
            speech.stop()
            // Give the final result a beat to land, then auto-send if enabled.
            let finalText = draft.trimmingCharacters(in: .whitespacesAndNewlines)
            if settings?.autoSendAfterSpeech == true, !finalText.isEmpty {
                send(finalText)
            }
        } else {
            draft = ""
            speech.start()
        }
    }

    // MARK: - Connection helpers

    func connectIfPossible() {
        guard let settings = settings, let mqtt = mqtt else { return }
        if settings.isConfigured, !mqtt.isConnected {
            mqtt.connect(using: settings)
        }
    }

    func note(_ text: String) {
        messages.append(ChatMessage(role: .system, text: text))
    }

    private func speakOnPhone(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-GB")
        synthesizer.speak(utterance)
    }
}
