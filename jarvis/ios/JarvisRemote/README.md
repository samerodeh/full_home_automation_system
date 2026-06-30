# JarvisRemote (iOS)

A SwiftUI app to chat with your Mac-side Jarvis from your phone — type or
**speak** a command (on-device speech-to-text), and Jarvis runs it exactly as
if you'd spoken to it in the room: it controls lights, plays Quran/athan, sets
reminders, answers questions, **speaks the reply aloud on the Mac**, and sends
the reply text back to your phone.

It works from **anywhere** (cellular included) over **Tailscale** — no router
config, no exposing anything to the public internet.

```
Phone (Tailscale) ──jarvis/command {id,text}──► Mac mosquitto ──► Jarvis (handle)
Phone (Tailscale) ◄──jarvis/reply  {id,text}── Mac mosquitto ◄── Jarvis (reply)
```

## How it talks to Jarvis

MQTT. The phone publishes JSON to `jarvis/command` and subscribes to
`jarvis/reply`. The Mac runs a small `mosquitto` broker that Jarvis's
`remote.py` bridge is subscribed to. See `../../mac/voice/remote/remote.py` and
`../../mac/voice/remote/mosquitto.conf`.

---

## One-time setup

### 1. On the Mac (broker + Tailscale)

```bash
brew install mosquitto
# create the broker user (matches REMOTE_USERNAME/REMOTE_PASSWORD in voice/.env)
mosquitto_passwd -c /opt/homebrew/etc/mosquitto/passwd jarvis
# run the broker with the provided config
mosquitto -c .../mac/voice/remote/mosquitto.conf      # or: brew services start mosquitto

brew install --cask tailscale                  # sign in
tailscale ip -4                                # note the 100.x.y.z address
```

Make sure `voice/.env` has `REMOTE_ENABLED=true` and the matching
`REMOTE_USERNAME` / `REMOTE_PASSWORD`, then (re)start Jarvis. You should see:
`[remote] phone bridge live on 127.0.0.1:1883`.

### 2. On the phone

Install **Tailscale** from the App Store and sign into the **same** account, so
the phone can reach the Mac's `100.x.y.z` from anywhere.

### 3. Build the app in Xcode

1. **Create the project:** Xcode → New → App → SwiftUI, name it `JarvisRemote`,
   minimum deployment **iOS 16**.
2. **Add the source files:** delete Xcode's default `ContentView.swift`, then
   drag every `.swift` file in this folder (keep the folder groups: `Models/`,
   `Services/`, `ViewModels/`, `Views/`, plus the top-level files) into the
   project. Check "Copy items if needed" + your app target.
3. **Add CocoaMQTT:** File → Add Package Dependencies →
   `https://github.com/emqx/CocoaMQTT.git`, rule **Up to Next Major 2.1.0**,
   add the **CocoaMQTT** product to the app target.
4. **Privacy strings:** add the two keys in `Info-plist-keys.md` to the target.
5. **Signing:** select your team + a unique bundle id.
6. **Run** on the Simulator (point Settings at the Mac's Tailscale IP — the
   Simulator shares the Mac's network) or on your device.

### 4. Configure the app

Open **Settings** (gear icon) and fill in:
- **Host:** the Mac's Tailscale IP (`100.x.y.z`)
- **Port:** `1883`
- **Username / Password:** the `mosquitto_passwd` credentials
- **Topics:** `jarvis/command` / `jarvis/reply` (defaults)

Tap **Connect**. The status dot turns green. Type or hit the mic and talk.

---

## Files

| File | Role |
|------|------|
| `JarvisRemoteApp.swift` | App entry; owns the shared objects |
| `ContentView.swift` | Root nav + Settings shortcut |
| `Models/ChatMessage.swift` | A chat bubble |
| `Models/AppSettings.swift` | Persisted connection/behavior settings |
| `Services/MQTTService.swift` | CocoaMQTT wrapper (publish/subscribe) |
| `Services/SpeechRecognizer.swift` | On-device STT (Speech + AVAudioEngine) |
| `ViewModels/ChatViewModel.swift` | Sends commands, receives replies, dictation |
| `Views/ChatView.swift` | Transcript + input bar + mic button |
| `Views/SettingsView.swift` | Broker/auth/topics/behavior form |

## Notes & limits

- **CocoaMQTT version:** code targets the 2.1.x delegate API. If you pin a
  different major, Xcode may flag delegate signature differences — adjust to
  match.
- **On-device STT** is requested when the device supports it (private, offline).
- Replies are matched by the echoed message `id`, so the app ignores stray
  messages.
- This is a LAN/Tailscale tool with broker password auth; transport encryption
  comes from Tailscale. There's no separate TLS on the broker (not needed
  inside the tunnel).
