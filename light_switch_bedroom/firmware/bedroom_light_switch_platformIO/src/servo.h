#pragma once
#include <Arduino.h>

// Initialize the servo pins and settings
void initServo();

// Trigger the 0 -> 70 -> 0 movement
void startServoSequence();

// Non-blocking update function to be called in loop()
void updateServoSequence();