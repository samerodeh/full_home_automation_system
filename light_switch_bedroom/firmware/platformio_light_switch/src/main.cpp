#include <Arduino.h>
#include "servo.h"
#include "mqtt.h"

void setup() {
    Serial.begin(115200);
    initServo();
    initMQTT();
}

void loop() {
    mqttLoop();
    updateServoSequence();
}
