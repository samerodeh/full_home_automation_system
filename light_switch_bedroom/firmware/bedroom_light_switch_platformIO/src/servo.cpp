#include "servo.h"
#include <ESP32Servo.h>

const int SERVO_PIN = 13;
const int SERVO_STEP_DELAY_MS = 400;
const int SERVO_SEQUENCE_ANGLE = 70;

static Servo servo;

enum ServoState { IDLE, MOVING_TO_OPEN, MOVING_TO_CLOSED };
struct {
    ServoState state = IDLE;
    unsigned long lastMoveTime = 0;
    int moveStep = 0;
} servoState;

void initServo()
{
    servo.attach(SERVO_PIN);
    Serial.print("Servo attached to pin: ");
    Serial.println(SERVO_PIN);
    startServoSequence();
}

void startServoSequence()
{
    Serial.println("Starting servo move sequence: 0 -> 70 -> 0");
    servoState.state = MOVING_TO_OPEN;
    servoState.moveStep = 0;
    servoState.lastMoveTime = millis();
    servo.write(0);
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
        Serial.println("Servo -> 70");
        servo.write(SERVO_SEQUENCE_ANGLE);
    }
    else if (servoState.moveStep == 2)
    {
        Serial.println("Servo -> 0");
        servo.write(0);
        servoState.state = IDLE;
    }
}
