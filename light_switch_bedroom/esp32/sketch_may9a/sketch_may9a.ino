void setup() {
  Serial.begin(57600);
  pinMode(2, OUTPUT);   // built-in LED on many ESP32 boards
}

void loop() {
  digitalWrite(2, HIGH);
  Serial.println("LED ON");
  delay(1000);

  digitalWrite(2, LOW);
  Serial.println("LED OFF");
  delay(1000);
}