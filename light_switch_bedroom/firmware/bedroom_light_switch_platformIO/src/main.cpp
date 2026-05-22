#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "secrets.h"

const int SERVO_PIN = 18;
const int SERVO_CHANNEL = 0;
const int SERVO_FREQ = 50;
const int SERVO_RES_BITS = 16;
const int SERVO_MIN_PULSE_US = 544;
const int SERVO_MAX_PULSE_US = 2400;
const int SERVO_STEP_DELAY_MS = 400;
const int SERVO_SEQUENCE_ANGLE = 70;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

enum ServoState { IDLE, MOVING_TO_OPEN, MOVING_TO_CLOSED };
struct {
    ServoState state = IDLE;
    unsigned long lastMoveTime = 0;
    int moveStep = 0;
} servoState;

int angleToDuty(int angle)
{
    int pulse = map(angle, 0, 180, SERVO_MIN_PULSE_US, SERVO_MAX_PULSE_US);
    return (int)((pulse / 20000.0) * ((1 << SERVO_RES_BITS) - 1));
}

void writeServoAngle(int angle)
{
    int duty = angleToDuty(angle);
    Serial.print("Servo write: angle=");
    Serial.print(angle);
    Serial.print(" duty=");
    Serial.println(duty);
    ledcWrite(SERVO_CHANNEL, duty);
}

void startServoSequence()
{
    Serial.println("Starting servo move sequence: 0 -> 70 -> 0");
    servoState.state = MOVING_TO_OPEN;
    servoState.moveStep = 0;
    servoState.lastMoveTime = millis();
    writeServoAngle(0);
}

void updateServoSequence()
{
    if (servoState.state == IDLE) return;

    unsigned long now = millis();
    if (now - servoState.lastMoveTime < SERVO_STEP_DELAY_MS) return;

    servoState.lastMoveTime = now;
    servoState.moveStep++;

    if (servoState.moveStep == 1)
    {
        writeServoAngle(SERVO_SEQUENCE_ANGLE);
    }
    else if (servoState.moveStep == 2)
    {
        writeServoAngle(0);
        servoState.state = IDLE;
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length)
{
    Serial.print("Message on topic: ");
    Serial.println(topic);

    String message;
    for (unsigned int i = 0; i < length; i++)
    {
        message += (char)payload[i];
    }

    message.trim();
    Serial.print("Payload: ");
    Serial.println(message);
    Serial.println("------------------");

    if (String(topic) == "home/bedroom/light/set")
    {
        startServoSequence();
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

    pinMode(SERVO_PIN, OUTPUT);
    ledcSetup(SERVO_CHANNEL, SERVO_FREQ, SERVO_RES_BITS);
    ledcAttachPin(SERVO_PIN, SERVO_CHANNEL);
    Serial.print("Servo pin: ");
    Serial.println(SERVO_PIN);
    startServoSequence();

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

    updateServoSequence();

    unsigned long now = millis();
    if (now - lastStatus > 10000)
    {
        Serial.print("MQTT connected: ");
        Serial.println(mqttClient.connected());
        lastStatus = now;
    }
}