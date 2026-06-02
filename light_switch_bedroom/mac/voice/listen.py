import whisper
import sounddevice as sd
import numpy as np
import paho.mqtt.client as mqtt

BROKER      = "192.168.2.38"
PORT        = 1883
TOPIC       = "home/bedroom/light/set"
SAMPLE_RATE = 16000
DURATION    = 3  # seconds to record after keypress

print("Loading Whisper model...")
model = whisper.load_model("base")
print("Model ready.\n")

client = mqtt.Client()
client.connect(BROKER, PORT)

def record():
    print(f"  Recording {DURATION}s...", end=" ", flush=True)
    audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    print("done.")
    return audio.flatten()

def transcribe(audio):
    result = model.transcribe(audio, fp16=False, language="en")
    return result["text"].strip().lower()

def handle(text):
    print(f"  Heard: \"{text}\"")
    if "off" in text:
        client.publish(TOPIC, "OFF")
        print("  → Published OFF\n")
    elif "on" in text:
        client.publish(TOPIC, "ON")
        print("  → Published ON\n")
    else:
        print("  → No command detected\n")

print("Press Enter to speak, Ctrl+C to quit.\n")
while True:
    try:
        input("[ Press Enter ]")
        audio = record()
        text  = transcribe(audio)
        handle(text)
    except KeyboardInterrupt:
        print("\nBye.")
        client.disconnect()
        break
