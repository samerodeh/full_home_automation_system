#include "servo.h"
#include <ESP32Servo.h>

static const int STEP_DELAY_MS = 400;
static const int NEUTRAL_ANGLE = 90;
static const int PRESS_OFFSET  = 70;
static const int PRESS_ANGLE   = NEUTRAL_ANGLE + PRESS_OFFSET;

enum class State { IDLE, STEP_ONE, STEP_TWO };

struct ServoCtrl {
    Servo         servo;
    int           pin;
    const char*   name;
    State         state;
    int           step;
    unsigned long lastStep;
};

static ServoCtrl servoOn  = { Servo(), 27, "ON",  State::IDLE, 0, 0 };
static ServoCtrl servoOff = { Servo(), 13, "OFF", State::IDLE, 0, 0 };

void initServo() {
    servoOn.servo.attach(servoOn.pin);
    servoOn.servo.write(NEUTRAL_ANGLE);

    servoOff.servo.attach(servoOff.pin);
    servoOff.servo.write(NEUTRAL_ANGLE);
}

static void startSequence(ServoCtrl& s) {
    Serial.print("Servo ");
    Serial.print(s.name);
    Serial.println(": press sequence");
    s.step     = 0;
    s.state    = State::STEP_ONE;
    s.lastStep = millis();
    s.servo.write(NEUTRAL_ANGLE);
}

void startServoOn()  { startSequence(servoOn);  }
void startServoOff() { startSequence(servoOff); }

static void updateOne(ServoCtrl& s) {
    if (s.state == State::IDLE) return;
    if (millis() - s.lastStep < STEP_DELAY_MS) return;

    s.lastStep = millis();
    s.step++;

    if (s.step == 1) {
        s.servo.write(PRESS_ANGLE);
        Serial.print("Servo "); Serial.print(s.name); Serial.println(" -> press");
        s.state = State::STEP_TWO;
    } else if (s.step == 2) {
        s.servo.write(NEUTRAL_ANGLE);
        Serial.print("Servo "); Serial.print(s.name); Serial.println(" -> neutral (done)");
        s.state = State::IDLE;
    }
}

void updateServoSequence() {
    updateOne(servoOn);
    updateOne(servoOff);
}
