//
//  SettingsView.swift
//  JarvisRemote
//
//  Connection + behavior settings. Mirrors the REMOTE_* values in the Mac's
//  Jarvis .env. Host = the Mac's Tailscale IP (`tailscale ip -4`).
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var mqtt: MQTTService

    @State private var portText: String = ""

    var body: some View {
        Form {
            Section("Broker (Mac over Tailscale)") {
                LabeledContent("Host") {
                    TextField("100.x.y.z", text: $settings.host)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.numbersAndPunctuation)
                }
                LabeledContent("Port") {
                    TextField("1883", text: $portText)
                        .multilineTextAlignment(.trailing)
                        .keyboardType(.numberPad)
                        .onChange(of: portText) { newValue in
                            settings.port = Int(newValue) ?? 1883
                        }
                }
            }

            Section("Auth") {
                LabeledContent("Username") {
                    TextField("jarvis", text: $settings.username)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                LabeledContent("Password") {
                    SecureField("•••••", text: $settings.password)
                        .multilineTextAlignment(.trailing)
                }
            }

            Section("Topics") {
                LabeledContent("Command") {
                    TextField("jarvis/command", text: $settings.commandTopic)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                LabeledContent("Reply") {
                    TextField("jarvis/reply", text: $settings.replyTopic)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
            }

            Section("Behavior") {
                Toggle("Auto-send after speaking", isOn: $settings.autoSendAfterSpeech)
                Toggle("Speak replies on phone", isOn: $settings.speakRepliesOnPhone)
            }

            Section {
                Button {
                    mqtt.connect(using: settings)
                } label: {
                    Label("Connect / Reconnect", systemImage: "antenna.radiowaves.left.and.right")
                }
                .disabled(!settings.isConfigured)
            } footer: {
                Text(statusFooter)
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { portText = String(settings.port) }
    }

    private var statusFooter: String {
        switch mqtt.status {
        case .connected: return "Connected."
        case .connecting: return "Connecting…"
        case .disconnected: return "Not connected."
        case .error(let msg): return msg
        }
    }
}

#Preview {
    NavigationStack { SettingsView() }
        .environmentObject(AppSettings())
        .environmentObject(MQTTService())
}
