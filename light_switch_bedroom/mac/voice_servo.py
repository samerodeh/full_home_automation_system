import speech_recognition as sr
import requests

# Replace this later with your ESP32 IP
ESP32_IP = "192.168.1.88"

recognizer = sr.Recognizer()

print("Voice control started.")
print("Say: 'turn on' or 'turn off'")

while True:
    with sr.Microphone() as source:
        print("\nListening...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio).lower()
        print("You said:", text)

        if "turn on" in text:
            requests.get(f"http://{ESP32_IP}/on")
            print("Sent: ON")

        elif "turn off" in text:
            requests.get(f"http://{ESP32_IP}/off")
            print("Sent: OFF")

        else:
            print("No command detected.")

    except sr.UnknownValueError:
        print("Could not understand.")

    except requests.ConnectionError:
        print("Cannot reach ESP32 yet (that’s okay for now).")

    except Exception as e:
        print("Error:", e)