# Required Info.plist privacy keys

Add these two keys to the app target (Xcode → target → **Info** tab → add rows,
or paste into `Info.plist` source). Both are mandatory — the app crashes on
first mic/speech use without them.

```xml
<key>NSMicrophoneUsageDescription</key>
<string>JarvisRemote uses the microphone to let you dictate commands to Jarvis.</string>

<key>NSSpeechRecognitionUsageDescription</key>
<string>JarvisRemote transcribes your speech on-device to send text commands to Jarvis.</string>
```

> Note: the broker connection is plain MQTT over TCP (port 1883). That's fine
> here because the traffic rides inside Tailscale's encrypted tunnel and never
> touches the public internet, so no `NSAppTransportSecurity` exception is
> needed for a `100.x.y.z` Tailscale address. If you ever point the app at a
> non-Tailscale host over plain TCP, add an ATS exception for it.
