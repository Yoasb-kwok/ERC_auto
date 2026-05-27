#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <Servo.h>
// BTS7960 Motor Driver Pins
#define L_EN D1 // Left Enable
#define R_EN D2 // Right Enable
#define L_PWM D5 // Left PWM
#define R_PWM D6 // Right PWM
// Servo Motor Pin
#define SERVO_PIN D3 // Servo control pin
#define ESC_PIN D4
// WiFi AP settings (matching your Python code)
const char* ssid = "Hagen_car6"; // You can change this
const char* password = "Hagen1234"; // You can change this
// UDP settings
WiFiUDP Udp;
unsigned int localUdpPort = 4210; // Listen on port 4210
char incomingPacket[255]; // Buffer for incoming packets
// Servo object
Servo frontServo;
Servo esc;
#define NEUTRAL_PULSE 1500
#define MAX_FORWARD 2000
#define MAX_REVERSE 1000
// Current motor and servo states
int left_speed = 0; // Backward speed (0-255 from Python)
int right_speed = 0; // Forward speed (0-255 from Python)
int brake_state = 0; // Emergency brake
int servo_angle = 90; // Servo angle (0-180)
int last_servo_angle = 90; // Track last servo position
void setup() {
Serial.begin(115200);
// Set PWM range to 1023 (ESP8266 default is 1023, but let's be
explicit)
analogWriteRange(1023);
esc.attach(ESC_PIN, 1000, 2000);
esc.writeMicroseconds(NEUTRAL_PULSE);
// Initialize motor driver pins
pinMode(L_EN, OUTPUT);
pinMode(R_EN, OUTPUT);
pinMode(L_PWM, OUTPUT);
pinMode(R_PWM, OUTPUT);
// Enable motor driver
digitalWrite(L_EN, HIGH);
digitalWrite(R_EN, HIGH);
// Start with motors stopped
analogWrite(L_PWM, 0);
analogWrite(R_PWM, 0);
// Initialize servo with better compatibility settings
frontServo.attach(SERVO_PIN, 500, 2400); // Min: 500µs, Max: 2400µs
pulse width
delay(100); // Give servo time to initialize
frontServo.write(90); // Center position
delay(500); // Wait for servo to reach center position
Serial.println("Servo initialized and centered");
// Initialize servo
frontServo.attach(SERVO_PIN);
frontServo.write(90); // Center position
// Configure WiFi as Access Point
WiFi.softAP(ssid, password);
IPAddress myIP = WiFi.softAPIP();
Serial.print("AP IP address: ");
Serial.println(myIP);
// Start UDP server
Udp.begin(localUdpPort);
Serial.printf("Now listening at IP %s, UDP port %d\n",
myIP.toString().c_str(), localUdpPort);
Serial.println("NodeMCU Robot Car Controller Ready!");
Serial.println("PWM Range: 0-1023 (ESP8266 default)");
//testServo();
}
void loop() {
// Check for incoming UDP packets
int packetSize = Udp.parsePacket();
if (packetSize) {
// Read the incoming packet
int len = Udp.read(incomingPacket, 255);
if (len > 0) {
incomingPacket[len] = 0; // Null terminate string
}
// Parse the command string
// Expected format: "L:0,R:110,B:0,S:120"
parseCommand(String(incomingPacket));
// Control motors and servo
controlMotors();
controlServo();
// Debug output
Serial.printf("Command: %s | L:%d R:%d B:%d S:%d\n",
incomingPacket, left_speed, right_speed, brake_state,
servo_angle);
}
delay(10); // Small delay
}
void parseCommand(String command) {
// Parse command format: "L:0,R:110,B:0,S:120"
left_speed = extractValue(command, "L:");
right_speed = extractValue(command, "R:");
brake_state = extractValue(command, "B:");
servo_angle = extractValue(command, "S:");
// Constrain values to safe ranges
left_speed = constrain(left_speed, 0, 255); // Python sends 0-255
right_speed = constrain(right_speed, 0, 255); // Python sends 0-255
brake_state = constrain(brake_state, 0, 1);
servo_angle = constrain(servo_angle, 0, 180);
}
int extractValue(String message, String key) {
int start = message.indexOf(key);
if (start == -1) return 0;
start += key.length(); // Move past the key
int end = message.indexOf(",", start);
if (end == -1) end = message.length();
String value = message.substring(start, end);
return value.toInt();
}
void controlMotors() {
// Convert 0-255 input range to 0-1023 ESP8266 PWM range
int left_pwm = map(left_speed, 0, 255, 0, 1023); // Scale to
ESP8266 range
int right_pwm = map(right_speed, 0, 255, 0, 1023); // Scale to
ESP8266 range
if (brake_state == 1) {
// Emergency stop - brake engaged
analogWrite(L_PWM, 0);
analogWrite(R_PWM, 0);
Serial.println("EMERGENCY BRAKE ENGAGED");
}
else if (right_speed > 0) {
// Forward movement
analogWrite(L_PWM, 0); // Use scaled PWM value
analogWrite(R_PWM, right_pwm);
Serial.printf("FORWARD: PWM=%d (scaled from %d)\n", right_pwm,
right_speed);
}
else if (left_speed > 0) {
// Backward movement
analogWrite(L_PWM, left_pwm);
analogWrite(R_PWM, 0); // Use scaled PWM value
Serial.printf("BACKWARD: PWM=%d (scaled from %d)\n", left_pwm,
left_speed);
}
else {
// No movement
analogWrite(L_PWM, 0);
analogWrite(R_PWM, 0);
}
}
void controlServo() {
if (servo_angle != last_servo_angle) {
frontServo.write(servo_angle);
last_servo_angle = servo_angle;
Serial.printf("Servo moved to: %d degrees\n", servo_angle);
delay(15); // Give servo time to move
}
}
void testServo() {
Serial.println("Testing servo movement...");
// Test sequence: Center -> Left -> Center -> Right -> Center
frontServo.write(90); // Center
delay(1000);
Serial.println("Servo: Center (90°)");
frontServo.write(45); // Left
delay(1000);
Serial.println("Servo: Left (45°)");
frontServo.write(90); // Center
delay(1000);
Serial.println("Servo: Center (90°)");
frontServo.write(135); // Right
delay(1000);
Serial.println("Servo: Right (135°)");
frontServo.write(90); // Center
delay(1000);
Serial.println("Servo: Back to center (90°)");
}
Serial.println("Servo test complete!");
