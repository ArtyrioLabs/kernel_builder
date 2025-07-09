#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Ticker.h>

LiquidCrystal_I2C lcd(0x27, 16, 2); 

const char* ssid = "";
const char* password = "";

ESP8266WebServer server(80);

const int buzzerPin = D5;
const int ledPin = LED_BUILTIN;

Ticker timer;
unsigned long startTime = 0;
bool isBuilding = false;

void setup() {
  Serial.begin(115200);
  
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Initializing...");
  
  pinMode(buzzerPin, OUTPUT);
  pinMode(ledPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);
  digitalWrite(ledPin, HIGH);
  
  WiFi.begin(ssid, password);
  lcd.setCursor(0, 1);
  lcd.print("Connecting WiFi");
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    digitalWrite(ledPin, !digitalRead(ledPin));
  }
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("IP:");
  lcd.setCursor(0, 1);
  lcd.print(WiFi.localIP());
  
  server.on("/", handleRoot);
  server.on("/display", handleDisplay);
  server.begin();
  
  delay(2000);
  lcd.clear();
  lcd.print("Ready for build");
  playReadySound();
  digitalWrite(ledPin, HIGH);
}

void loop() {
  server.handleClient();
}

void handleRoot() {
  server.send(200, "text/plain", "ESP8266 Build Monitor");
}

void handleDisplay() {
  String message = server.arg("text");
  
  if (message == "Build Started") {
    startBuild();
    server.send(200, "text/plain", "Build started");
    return;
  }
  
  if (message == "Build Success") {
    endBuild(true);
    server.send(200, "text/plain", "Build success");
    return;
  }
  
  if (message == "Build Failed") {
    endBuild(false);
    server.send(200, "text/plain", "Build failed");
    return;
  }
  
  updateDisplay(message);
  server.send(200, "text/plain", "Message displayed");
}

void startBuild() {
  isBuilding = true;
  startTime = millis();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Build started!");
  digitalWrite(ledPin, LOW);
  
  for(int i = 0; i < 3; i++) {
    tone(buzzerPin, 800 + i*200);
    delay(80);
    noTone(buzzerPin);
    delay(50);
  }
  
  timer.attach(1, updateTimer);
}

void endBuild(bool success) {
  isBuilding = false;
  timer.detach();
  
  unsigned long duration = (millis() - startTime) / 1000;
  int minutes = duration / 60;
  int seconds = duration % 60;
  
  lcd.clear();
  lcd.setCursor(0, 0);
  
  if (success) {
    lcd.print("Build SUCCESS!");
    playSuccessSound();
    digitalWrite(ledPin, HIGH);
  } else {
    lcd.print("Build FAILED!");
    playErrorSound();
    blinkLED(5, 200);
  }
  
  lcd.setCursor(0, 1);
  lcd.print("Time: ");
  if (minutes > 0) lcd.print(String(minutes) + "m ");
  lcd.print(String(seconds) + "s");
}

void updateTimer() {
  if (!isBuilding) return;
  
  unsigned long duration = (millis() - startTime) / 1000;
  int minutes = duration / 60;
  int seconds = duration % 60;
  
  lcd.setCursor(0, 1);
  lcd.print("Time: ");
  if (minutes > 0) lcd.print(String(minutes) + "m ");
  lcd.print(String(seconds) + "s  ");
}

void updateDisplay(String message) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(message.substring(0, 16));
  lcd.setCursor(0, 1);
  lcd.print(message.substring(16, 32));
}

void playReadySound() {
  tone(buzzerPin, 1200, 80);
  delay(100);
  tone(buzzerPin, 1200, 80);
  delay(100);
  noTone(buzzerPin);
}

void playSuccessSound() {
  tone(buzzerPin, 523, 150); 
  delay(170);
  tone(buzzerPin, 659, 150); 
  delay(170);
  tone(buzzerPin, 784, 300); 
  delay(350);
  noTone(buzzerPin);
}

void playErrorSound() {
  for (int i = 0; i < 3; i++) {
    tone(buzzerPin, 1200); 
    delay(150);
    noTone(buzzerPin);
    delay(100);
  }
  
  tone(buzzerPin, 300);
  delay(300);
  noTone(buzzerPin);
} 

void blinkLED(int count, int interval) {
  for(int i = 0; i < count; i++) {
    digitalWrite(ledPin, LOW);
    delay(interval);
    digitalWrite(ledPin, HIGH);
    delay(interval);
  }
}