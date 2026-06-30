//
//  ChatMessage.swift
//  JarvisRemote
//
//  One bubble in the chat transcript.
//

import Foundation

struct ChatMessage: Identifiable, Equatable {
    enum Role {
        case user       // what you sent to Jarvis
        case assistant  // Jarvis's reply
        case system     // local status notes (connecting, errors)
    }

    let id: String
    let role: Role
    var text: String
    let timestamp: Date

    init(id: String = UUID().uuidString,
         role: Role,
         text: String,
         timestamp: Date = Date()) {
        self.id = id
        self.role = role
        self.text = text
        self.timestamp = timestamp
    }
}
