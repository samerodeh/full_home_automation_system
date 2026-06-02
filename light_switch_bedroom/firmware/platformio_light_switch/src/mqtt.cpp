#include "mqtt.h"
#include "servo.h"
#include "secrets.h"
#include <WiFi.h>
#include <PubSubClient.h>

static const char* MQTT_CLIENT_ID = "bedroom_light_switch";
static const char* MQTT_TOPIC     = "home/bedroom/light/set";

static WiFiClient   wifiClient;
static PubSubClient mqtt(wifiClient);

static void connectWiFi() {
    Serial.print("Connecting to Wi-Fi");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("Wi-Fi connected — IP: ");
    Serial.println(WiFi.localIP());
}

static void onMessage(char* topic, byte* payload, unsigned int length) {
    String msg;
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
    msg.trim();

    Serial.print("MQTT [");
    Serial.print(topic);
    Serial.print("]: ");
    Serial.println(msg);

    if (String(topic) == MQTT_TOPIC) {
        if (msg == "ON")  startServoOn();
        if (msg == "OFF") startServoOff();
    }
}

static void connectMQTT() {
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setCallback(onMessage);

    while (!mqtt.connected()) {
        Serial.print("Connecting to MQTT...");
        if (mqtt.connect(MQTT_CLIENT_ID)) {
            Serial.println(" connected!");
            mqtt.subscribe(MQTT_TOPIC);
            Serial.print("Subscribed to: ");
            Serial.println(MQTT_TOPIC);
        } else {
            Serial.print(" failed (state=");
            Serial.print(mqtt.state());
            Serial.println("), retrying in 2s");
            delay(2000);
        }
    }
}

void initMQTT() {
    connectWiFi();
    connectMQTT();
}

void mqttLoop() {
    if (!mqtt.connected()) {
        connectMQTT();
    }
    mqtt.loop();
}
