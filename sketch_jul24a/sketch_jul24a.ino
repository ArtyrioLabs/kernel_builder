#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Ticker.h> 
#include <SPI.h> 
#include <SdFat.h>
#define SD_CS_PIN D8 // Chip Select для SD-карты
// Используем стандартные SPI-пины ESP8266:
// SCK  = D5 (GPIO14)
// MISO = D6 (GPIO12)
// MOSI = D7 (GPIO13)
// CS   = D8 (GPIO15)

LiquidCrystal_I2C lcd(0x27, 16, 2); 

const char* ssid = "YOUR_WIFI_SSID"; 
const char* password = "YOUR_WIFI_PASSWORD"; 

ESP8266WebServer server(80);

const int buzzerPin = D5;
const int ledPin = LED_BUILTIN;

Ticker timer;
unsigned long startTime = 0;
bool isBuilding = false;

SdFat SD;
String logFileName = "/log.txt";

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
  
  // SD-карта через SdFat
  if (!SD.begin(SD_CS_PIN)) {
    lcd.clear();
    lcd.print("SD init failed!");
    delay(2000);
  } else {
    uint32_t totalClusters = SD.vol()->clusterCount();
    uint32_t sectorsPerCluster = SD.vol()->sectorsPerCluster();
    uint64_t totalBytes = (uint64_t)totalClusters * sectorsPerCluster * 512;
    lcd.clear();
    lcd.print("SD ready!");
    lcd.setCursor(0, 1);
    lcd.print("Size:");
    lcd.print(totalBytes / (1024 * 1024));
    lcd.print("MB");
    delay(2000);
  }

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
  server.on("/log", handleLog); 
  server.on("/sdinfo", handleSDInfo); 
  server.on("/ls", handleListFiles);
  server.on("/download", handleDownload);
  server.on("/delete", handleDelete);
  server.on("/clearlog", handleClearLog);
  server.on("/setlogname", handleSetLogName);
  server.on("/upload", HTTP_POST, handleUpload);
  server.on("/webui", handleWebUI);
  server.on("/reboot", handleReboot);
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
  logToSD("Display: " + message);
  
  if (message == "Build Started") {
    startBuild();
    logToSD("Build started!");
    server.send(200, "text/plain", "Build started");
    return;
  }
  
  if (message == "Build Success") {
    endBuild(true);
    logToSD("Build SUCCESS!");
    server.send(200, "text/plain", "Build success");
    return;
  }
  
  if (message == "Build Failed") {
    endBuild(false);
    logToSD("Build FAILED!");
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
  logToSD("Build started!");
  
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
    logToSD("Build SUCCESS!");
  } else {
    lcd.print("Build FAILED!");
    playErrorSound();
    blinkLED(5, 200);
    logToSD("Build FAILED!");
  }
  
  lcd.setCursor(0, 1);
  lcd.print("Time: ");
  if (minutes > 0) lcd.print(String(minutes) + "m ");
  lcd.print(String(seconds) + "s");
  logToSD("Build time: " + String(minutes) + "m " + String(seconds) + "s");
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

void logToSD(const String& msg) {
  autoCleanLogs();
  FsFile logFile = SD.open(logFileName.c_str(), FILE_WRITE);
  if (logFile) {
    logFile.print("[");
    logFile.print(millis()/1000);
    logFile.print("] ");
    logFile.println(msg);
    logFile.close();
  }
}

void handleLog() {
  FsFile logFile = SD.open(logFileName.c_str());
  if (logFile) {
    String content;
    while (logFile.available()) {
      content += (char)logFile.read();
    }
    logFile.close();
    server.send(200, "text/plain", content);
  } else {
    server.send(404, "text/plain", "No log file");
  }
}

void handleSDInfo() {
  if (!SD.begin(SD_CS_PIN)) {
    server.send(500, "text/plain", "SD init failed");
    return;
  }
  uint32_t totalClusters = SD.vol()->clusterCount();
  uint32_t freeClusters = SD.vol()->freeClusterCount();
  uint32_t sectorsPerCluster = SD.vol()->sectorsPerCluster();
  uint64_t totalBytes = (uint64_t)totalClusters * sectorsPerCluster * 512;
  uint64_t freeBytes = (uint64_t)freeClusters * sectorsPerCluster * 512;
  int fileCount = 0;
  FsFile dir = SD.open("/");
  while (true) {
    FsFile entry = dir.openNextFile();
    if (!entry) break;
    fileCount++;
    entry.close();
  }
  dir.close();
  String info = "total=" + String(totalBytes) + "\nfree=" + String(freeBytes) + "\nfiles=" + String(fileCount);
  server.send(200, "text/plain", info);
}

void handleListFiles() {
  String list = "";
  FsFile dir = SD.open("/");
  while (true) {
    FsFile entry = dir.openNextFile();
    if (!entry) break;
    char fname[64];
    entry.getName(fname, sizeof(fname));
    list += fname;
    list += " (";
    list += entry.size();
    list += " bytes)\n";
    entry.close();
  }
  dir.close();
  server.send(200, "text/plain", list);
}

void handleDownload() {
  String fname = server.arg("file");
  if (!fname.length()) {
    server.send(400, "text/plain", "No file specified");
    return;
  }
  FsFile file = SD.open(fname.c_str());
  if (!file) {
    server.send(404, "text/plain", "File not found");
    return;
  }
  server.setContentLength(file.size());
  server.send(200, "application/octet-stream", "");
  char buf[512];
  int n;
  while ((n = file.read(buf, sizeof(buf))) > 0) {
    server.sendContent_P(buf, n);
  }
  file.close();
}

void handleDelete() {
  String fname = server.arg("file");
  if (!fname.length()) {
    server.send(400, "text/plain", "No file specified");
    return;
  }
  if (SD.remove(fname.c_str())) {
    server.send(200, "text/plain", "File deleted");
  } else {
    server.send(404, "text/plain", "File not found or error");
  }
}

void handleClearLog() {
  if (SD.remove(logFileName.c_str())) {
    server.send(200, "text/plain", "Log cleared");
  } else {
    server.send(200, "text/plain", "Log already empty");
  }
}

void handleSetLogName() {
  String name = server.arg("name");
  if (name.length() > 0 && name[0] != '/') name = "/" + name;
  logFileName = name;
  server.send(200, "text/plain", "Log file name set to: " + logFileName);
}

void handleUpload() {
  if (server.hasArg("plain")) {
    String fname = server.arg("file");
    if (!fname.length()) fname = "/upload.bin";
    FsFile file = SD.open(fname.c_str(), O_WRITE | O_CREAT | O_TRUNC);
    if (!file) {
      server.send(500, "text/plain", "Failed to open file");
      return;
    }
    file.write((const uint8_t*)server.arg("plain").c_str(), server.arg("plain").length());
    file.close();
    server.send(200, "text/plain", "File uploaded: " + fname);
  } else {
    server.send(400, "text/plain", "No data");
  }
}

void handleWebUI() {
  String html = "<html><body><h2>SD Card File Manager</h2>";
  html += "<form method='POST' action='/upload' enctype='text/plain'>File name: <input name='file'><br>Data:<br><textarea name='plain'></textarea><br><input type='submit' value='Upload'></form>";
  html += "<a href='/ls'>List Files</a><br>";
  html += "<form action='/delete'><input name='file'><input type='submit' value='Delete'></form>";
  html += "<form action='/clearlog'><input type='submit' value='Clear Log'></form>";
  html += "<form action='/reboot'><input type='submit' value='Reboot ESP'></form>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

void autoCleanLogs() {
  uint32_t freeClusters = SD.vol()->freeClusterCount();
  uint32_t sectorsPerCluster = SD.vol()->sectorsPerCluster();
  uint64_t freeBytes = (uint64_t)freeClusters * sectorsPerCluster * 512;
  if (freeBytes < 1024*1024) { // если меньше 1 МБ свободно
    SD.remove(logFileName.c_str());
  }
}

void handleReboot() {
  server.send(200, "text/plain", "Rebooting...");
  ESP.restart();
}