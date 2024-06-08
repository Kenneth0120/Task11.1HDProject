#include <ArduinoBLE.h>
#include <SPI.h>
#include <MFRC522.h>
#include <LiquidCrystal_I2C.h>
#include <Keypad.h>
#include <Wire.h>

// Bluetooth setup
#define SERVICE_UUID           "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
// BLE Variables
BLEService securityService(SERVICE_UUID); // create service
BLEStringCharacteristic rxCharacteristic(CHARACTERISTIC_UUID_RX, BLEWrite, 30);
BLEStringCharacteristic txCharacteristic(CHARACTERISTIC_UUID_TX, BLENotify, 30);

// RFID setup
#define SS_PIN 10
#define RST_PIN 9
MFRC522 mfrc522(SS_PIN, RST_PIN);
byte authorizedUID[4] = {0xD0, 0xE1, 0x26, 0x10}; // Authorized card UID
// LCD setup
LiquidCrystal_I2C lcd(0x3F, 16, 2);
// Keypad setup
const byte ROWS = 4;
const byte COLS = 3;
char keys[ROWS][COLS] = {{'1','2','3'}, {'4','5','6'}, {'7','8','9'}, {'*','0','#'}};
byte rowPins[ROWS] = {8, 7, 6, 5};
byte colPins[COLS] = {4, 3, 2};
// Microswitch setup
Keypad keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS);
int doorPins[2] = {A0, A1};
int windowPins[2] = {A2, A3};
// System state
bool systemDeactivated = true;
String enteredPassword = "";
String correctPassword = "575621";
// Global variables to keep track of door and window status changes
bool wasDoorWindowFault = false;
bool potentialBreakIn = false;
bool lastSystemActivated = true;
bool lastPotentialBreakIn = true;
bool lastlockSys = true;
bool lastdeactSys = true;

void setup() {
  Serial.begin(9600);
  while (!Serial);
  SPI.begin();
  mfrc522.PCD_Init();
  lcd.init();
  lcd.backlight();
  updateLCD();
  Serial.println("System Initialized");

  if (!BLE.begin()) {
    Serial.println("Starting BLE failed!");
    while (1);
  }

  BLE.setLocalName("SecuritySystem");
  BLE.setAdvertisedService(securityService);
  securityService.addCharacteristic(rxCharacteristic);
  securityService.addCharacteristic(txCharacteristic);
  BLE.addService(securityService);
  BLE.setEventHandler(BLEConnected, blePeripheralConnectHandler);
  BLE.setEventHandler(BLEDisconnected, blePeripheralDisconnectHandler);
  rxCharacteristic.setEventHandler(BLEWritten, rxCharacteristicWritten);
  rxCharacteristic.setValue("SecuritySystem");
  BLE.advertise();
  Serial.println(("Bluetooth device active, waiting for connections..."));
  Serial.println(BLE.address());


  /*
  BLE.setLocalName("SecuritySystem");
  BLE.setAdvertisedService(securityService);
  securityService.addCharacteristic(systemStateCharacteristic);
  BLE.addService(securityService);
  systemStateCharacteristic.writeValue("Locked");
  BLE.advertise();
  Serial.println("BLE service advertised");
  */
}

void loop() {
  BLE.poll();
  readKeypad();
  checkRFID();
  checkDoorsAndWindows();
  dataSend();
}

// Function to compare two UIDs
bool isAuthorizedUID(byte *scannedUID) {
  for (byte i = 0; i < 4; i++) {  // Assuming UID is 4 bytes
    if (scannedUID[i] != authorizedUID[i]) {
      return false;
    }
  }
  return true;
}

void readKeypad() {
  char key = keypad.getKey();
  if (key) {
    Serial.print("Keypad pressed: ");
    Serial.println(key);
    if (key == '#') {
      if (enteredPassword == correctPassword) {
        systemDeactivated = !systemDeactivated;
        enteredPassword = "";
        updateLCD();
        lastSystemActivated = true;
        //Serial.println(systemDeactivated);
        Serial.println("Password correct. System state toggled.");
      } else {
        enteredPassword = ""; // Reset password entry on fail
        Serial.println("Password incorrect. Entry reset.");
      }
    } else if (key == '*') {
      enteredPassword = ""; // Clear entered password
      Serial.println("Password entry cleared.");
    } else {
      enteredPassword += key;
    }
    lcd.setCursor(0, 1);
    lcd.print("Pass: " + enteredPassword + "      ");
  }
}

void checkRFID() {
  if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    /*
    Serial.print("Card UID:");
    for (byte i = 0; i < mfrc522.uid.size; i++) {
      Serial.print(mfrc522.uid.uidByte[i] < 0x10 ? " 0" : " ");
      Serial.print(mfrc522.uid.uidByte[i], HEX);
    }
    Serial.println();
    */
    // Check if the scanned card's UID matches the authorized UID
    if (isAuthorizedUID(mfrc522.uid.uidByte)) {
      systemDeactivated = !systemDeactivated;  // Toggle the system state
      updateLCD();
      //Serial.println(systemDeactivated);
      if (systemDeactivated) {
        lastSystemActivated = true;
        Serial.println("Security System Deactivated");
      } else {
        lastSystemActivated = true;
        Serial.println("Security System Locked");
      }
    } else {
      //Serial.println(systemDeactivated);
      lcd.setCursor(0, 1);
      lcd.print("Unauthoriz RFID");
      Serial.println("Unauthorized RFID attempted");
    }

    mfrc522.PICC_HaltA(); // Halt PICC
  }
}


void checkDoorsAndWindows() {
  // Read the current status of each door and window microswitch
  bool doorStatus1 = digitalRead(doorPins[0]);
  bool doorStatus2 = digitalRead(doorPins[1]);
  bool windowStatus1 = digitalRead(windowPins[0]);
  bool windowStatus2 = digitalRead(windowPins[1]);

  delay(100);
  if (!systemDeactivated) {
    // Check for door and window faults or break-ins
    if (doorStatus1 || doorStatus2 || windowStatus1 || windowStatus2) {
      if (!wasDoorWindowFault) {  // Only update if this is a new event
        lcd.clear();
        if ((doorStatus1 && !doorStatus2) || (!doorStatus1 && doorStatus2) ||
            (windowStatus1 && !windowStatus2) || (!windowStatus1 && windowStatus2)) {
          // Fault in one of the microswitches
          lcd.setCursor(0, 0);
          lcd.print("-----Check-----");
          lcd.setCursor(0, 1);
          lcd.print("-MSwitch Fault-");
          Serial.println("One microswitch fault detected.");
        } else if ((doorStatus1 && doorStatus2) || (windowStatus1 && windowStatus2)) {
          // Potential break-in (both switches open)
          lcd.setCursor(0, 0);
          lcd.print("---Potential---");
          lcd.setCursor(0, 1);
          lcd.print("---Break-in!---");
          Serial.println("Potential break-in detected.");
          potentialBreakIn = true;
          lastPotentialBreakIn = true;
        }
        wasDoorWindowFault = true;
      }
    } else if (wasDoorWindowFault) {
      updateLCD();
      Serial.println("Doors and Windows are secure.");
      wasDoorWindowFault = false;
      potentialBreakIn = false;
      lastPotentialBreakIn = true;
    }
  }
}

void updateLCD() {
  lcd.clear();
  lcd.setCursor(0, 0);
  if (systemDeactivated) {
    lcd.print("Sys: Deactivated");
    //Serial.println("LCD updated: System Deactivated");
  } else {
    lcd.print("Sys: Locked   ");
    //Serial.println("LCD updated: System Locked");
  }
}

void blePeripheralConnectHandler(BLEDevice central) {
  // central connected event handler
  Serial.print("Connected event, central: ");
  Serial.println(central.address());
}

void blePeripheralDisconnectHandler(BLEDevice central) {
  // central disconnected event handler
  Serial.print("Disconnected event, central: ");
  Serial.println(central.address());
}

void rxCharacteristicWritten(BLEDevice central, BLECharacteristic characteristic) {
  String receivedValue = rxCharacteristic.value();

  // Find the indexes of the commas
  int firstCommaIndex = receivedValue.indexOf(',');
  int secondCommaIndex = receivedValue.indexOf(',', firstCommaIndex + 1);

  // Extract each part of the data string
  String motionDetect = receivedValue.substring(0, firstCommaIndex);
  String lockSystem = receivedValue.substring(firstCommaIndex + 1, secondCommaIndex);
  String deactivateSystem = receivedValue.substring(secondCommaIndex + 1);

  // Convert string values to integer
  int moDetect = motionDetect.toInt();
  int lockSys = lockSystem.toInt();
  int deactSys = deactivateSystem.toInt();

  // Update system status based on the lock and deactivate signals
  if (lockSys == 1 && lastlockSys == true) {
    systemDeactivated = false; // Lock system indicates system should be active (not deactivated)
    updateLCD();
    Serial.println("System is now active (locked).");
    lastlockSys = false;
    lastdeactSys = true;
  } else if (deactSys == 1 && lastdeactSys == true) {
    systemDeactivated = true; // Deactivate system indicates system should be deactivated
    updateLCD();
    Serial.println("System is now deactivated.");
    lastlockSys = true;
    lastdeactSys = false;
  }

  // Debug print to Serial monitor
  Serial.print("Motion Detected: ");
  Serial.println(moDetect);
  Serial.print("Lock System: ");
  Serial.println(lockSys);
  Serial.print("Deactivate System: ");
  Serial.println(deactSys);
  Serial.println(".....................................");
}

void dataSend() {
  // Check if there's a change in state
  if (lastSystemActivated == true || lastPotentialBreakIn == true) {
    // Prepare data to send
    String dataToSend = String(systemDeactivated) + "," + String(potentialBreakIn);
    txCharacteristic.setValue(dataToSend);
    Serial.print("Sending data: ");
    Serial.println(dataToSend);

    // Update last known states
    lastSystemActivated = false;
    lastPotentialBreakIn = false;
  }
}