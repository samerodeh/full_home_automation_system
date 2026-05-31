#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "secrets.h"
#include "servo.h"

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

void mqttCallback(char* topic, byte* payload, unsigned int length)
{
    String message;

    for (unsigned int i = 0; i < length; i++)
        message += (char)payload[i];

    message.trim();

    Serial.print("MQTT: ");
    Serial.println(message);

    if (String(topic) == "home/bedroom/light/set")
    {
        if (message == "ON" || message == "OFF")
        {
            startServoSequence(); 
        }
    }
}

void connectWiFi()
{
    Serial.println("Connecting to Wi-Fi...");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.println("Wi-Fi connected!");
    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());
}

void connectMQTT()
{
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

    while (!mqttClient.connected())
    {
        Serial.println("Connecting to MQTT...");

        if (mqttClient.connect("bedroom_light_switch"))
        {
            Serial.println("MQTT connected!");
            if (mqttClient.subscribe("home/bedroom/light/set"))
            {
                Serial.println("Subscribed to home/bedroom/light/set");
            }
            else
            {
                Serial.println("MQTT subscribe failed");
            }
        }
        else
        {
            Serial.print("MQTT failed. state=");
            Serial.println(mqttClient.state());
            Serial.println("Retrying in 2 sec...");
            delay(2000);
        }
    }
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    // Call the setup function from servo.cpp
    initServo();

    connectWiFi();
    mqttClient.setCallback(mqttCallback);
    connectMQTT();
}

void loop()
{
    static unsigned long lastStatus = 0;
    
    if (!mqttClient.connected())
    {
        connectMQTT();
    }
    else
    {
        mqttClient.loop();
    }

    // Continuously check if the servo needs to step forward
    updateServoSequence();

    unsigned long now = millis();
    if (now - lastStatus > 10000)
    {
        Serial.print("MQTT connected: ");
        Serial.println(mqttClient.connected());
        lastStatus = now;
    }
}