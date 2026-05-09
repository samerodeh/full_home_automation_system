#include <WiFi.h>
#include <WebServer.h>
#include <ESP32Servo.h>

// ---------- WIFI ----------
const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";

// ---------- SERVER ----------
WebServer server(80);

// ---------- SERVO ----------
Servo myServo;
#define SERVO_PIN 12   // try GPIO13 if GPIO12 fails

// Move servo ON
void handleOn() {
  myServo.write(90);
  server.send(200, "text/plain", "Servo ON");
}

// Move servo OFF
void handleOff() {
  myServo.write(0);
  server.send(200, "text/plain", "Servo OFF");
}

void setup() {
  Serial.begin(115200);

  // Servo setup
  myServo.attach(SERVO_PIN);
  myServo.write(0);

  // Wi-Fi connect
  WiFi.begin(ssid, password);
  Serial.print("Connecting");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("Connected!");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());

  // Web routes
  server.on("/on", handleOn);
  server.on("/off", handleOff);

  server.begin();
  Serial.println("Web server started");
}

void loop() {
  server.handleClient();
}