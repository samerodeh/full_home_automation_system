//
//  ContentView.swift
//  JarvisRemote
//
//  Root view: the chat, with a toolbar shortcut to Settings.
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: AppSettings

    var body: some View {
        NavigationStack {
            ChatView()
                .navigationTitle("Jarvis")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        NavigationLink {
                            SettingsView()
                        } label: {
                            Image(systemName: "gearshape")
                        }
                    }
                }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppSettings())
        .environmentObject(MQTTService())
        .environmentObject(SpeechRecognizer())
}
