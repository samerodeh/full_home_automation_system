//
//  JarvisRemoteApp.swift
//  JarvisRemote
//
//  Entry point. Owns the long-lived AppSettings, MQTT service, and speech
//  recognizer and injects them into the view tree.
//

import SwiftUI

@main
struct JarvisRemoteApp: App {
    @StateObject private var settings = AppSettings()
    @StateObject private var mqtt = MQTTService()
    @StateObject private var speech = SpeechRecognizer()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(mqtt)
                .environmentObject(speech)
        }
    }
}
