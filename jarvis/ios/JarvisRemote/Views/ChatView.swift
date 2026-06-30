//
//  ChatView.swift
//  JarvisRemote
//
//  The chat screen: transcript bubbles + an input bar with a text field,
//  a mic (dictation) button, and a send button. A status dot shows the
//  broker connection.
//

import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var mqtt: MQTTService
    @EnvironmentObject private var speech: SpeechRecognizer
    @StateObject private var vm = ChatViewModel()

    var body: some View {
        VStack(spacing: 0) {
            statusBar
            transcript
            inputBar
        }
        .onAppear {
            vm.configure(settings: settings, mqtt: mqtt, speech: speech)
            speech.requestAuthorization()
            vm.connectIfPossible()
        }
    }

    // MARK: - Status

    private var statusBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(statusColor)
                .frame(width: 9, height: 9)
            Text(statusText)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            if !mqtt.isConnected {
                Button("Connect") { mqtt.connect(using: settings) }
                    .font(.caption.weight(.semibold))
                    .disabled(!settings.isConfigured)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 6)
        .background(.bar)
    }

    private var statusColor: Color {
        switch mqtt.status {
        case .connected: return .green
        case .connecting: return .yellow
        case .disconnected: return .gray
        case .error: return .red
        }
    }

    private var statusText: String {
        switch mqtt.status {
        case .connected: return "Connected to \(settings.host)"
        case .connecting: return "Connecting…"
        case .disconnected:
            return settings.isConfigured ? "Disconnected" : "Set the broker in Settings"
        case .error(let msg): return "Error: \(msg)"
        }
    }

    // MARK: - Transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    ForEach(vm.messages) { msg in
                        MessageBubble(message: msg).id(msg.id)
                    }
                }
                .padding()
            }
            .onChange(of: vm.messages.count) { _ in
                if let last = vm.messages.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    // MARK: - Input

    private var inputBar: some View {
        HStack(spacing: 10) {
            Button(action: vm.toggleDictation) {
                Image(systemName: vm.isRecording ? "mic.fill" : "mic")
                    .font(.title2)
                    .foregroundStyle(vm.isRecording ? .red : .accentColor)
                    .symbolEffect(.pulse, isActive: vm.isRecording)
            }

            TextField(vm.isRecording ? "Listening…" : "Message Jarvis", text: $vm.draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
                .onSubmit(vm.send)

            Button(action: vm.send) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title)
            }
            .disabled(vm.draft.trimmingCharacters(in: .whitespaces).isEmpty || !mqtt.isConnected)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }
}

// MARK: - Bubble

private struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 40) }
            Text(message.text)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(background)
                .foregroundStyle(foreground)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .frame(maxWidth: .infinity,
                       alignment: message.role == .user ? .trailing : .leading)
            if message.role != .user { Spacer(minLength: 40) }
        }
    }

    private var background: Color {
        switch message.role {
        case .user: return .accentColor
        case .assistant: return Color(.secondarySystemBackground)
        case .system: return .clear
        }
    }

    private var foreground: Color {
        switch message.role {
        case .user: return .white
        case .assistant: return .primary
        case .system: return .secondary
        }
    }
}
