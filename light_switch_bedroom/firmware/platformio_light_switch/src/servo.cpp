#include "servo.h"
#include <ESP32Servo.h>

static const int SERVO_PIN     = 13;
static const int STEP_DELAY_MS = 400;
static const int NEUTRAL_ANGLE = 90;
static const int PRESS_OFFSET  = 70;

static Servo servo;

enum class State { IDLE, STEP_ONE, STEP_TWO };

static State         servoState = State::IDLE;
static int           step       = 0;
static unsigned long lastStep   = 0;
static int           targetAngle = 0;

void initServo() {
    servo.attach(SERVO_PIN);
    servo.write(NEUTRAL_ANGLE);
}

static void startSequence(int target) {
    step        = 0;
    targetAngle = target;
    servoState  = State::STEP_ONE;
    lastStep    = millis();
    servo.write(NEUTRAL_ANGLE);
}

void startServoOn() {
    Serial.println("Servo: ON sequence");
    startSequence(NEUTRAL_ANGLE + PRESS_OFFSET);
}

void startServoOff() {
    Serial.println("Servo: OFF sequence");
    startSequence(NEUTRAL_ANGLE - PRESS_OFFSET);
}

void updateServoSequence() {
    if (servoState == State::IDLE) return;
    if (millis() - lastStep < STEP_DELAY_MS) return;

    lastStep = millis();
    step++;

    if (step == 1) {
        servo.write(targetAngle);
        Serial.print("Servo -> "); Serial.println(targetAngle);
        servoState = State::STEP_TWO;
    } else if (step == 2) {
        servo.write(NEUTRAL_ANGLE);
        Serial.println("Servo -> neutral (done)");
        servoState = State::IDLE;
    }
}
