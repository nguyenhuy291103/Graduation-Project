#ifndef PACKET_H
#define PACKET_H

#include <Arduino.h>

// =========================================
// PACKET TYPES
// =========================================

#define PACKET_REQUEST     "REQUEST"
#define PACKET_RESPONSE    "RESPONSE"
#define PACKET_EVENT       "EVENT"
#define PACKET_STATE       "STATE"
#define PACKET_ACK         "ACK"

// =========================================
// COMMANDS
// =========================================

// Contact
#define CMD_ADD_CONTACT    "ADD_CONTACT"

// SMS
#define CMD_SEND_SMS          "SEND_SMS"
#define CMD_NEW_SMS           "NEW_SMS"
#define CMD_SMS_SENT          "SMS_SENT"

// Manual SMS
#define CMD_START_MANUAL_SMS  "START_MANUAL_SMS"
#define CMD_STOP_MANUAL_SMS   "STOP_MANUAL_SMS"
#define CMD_SEND_MANUAL_SMS   "SEND_MANUAL_SMS"

// LCD
#define CMD_LCD_SHOW       "LCD_SHOW"

// System
#define CMD_HEARTBEAT      "HEARTBEAT"
#define CMD_SYSTEM_STATE   "SYSTEM_STATE"

// =========================================
// STATUS
// =========================================

#define STATUS_SUCCESS     "SUCCESS"
#define STATUS_ERROR       "ERROR"

// =========================================
// ERROR CODES
// =========================================

#define ERROR_PHONE_EXISTS     "PHONE_EXISTS"
#define ERROR_INVALID_PHONE    "INVALID_PHONE"
#define ERROR_ID_EXISTS        "ID_EXISTS"
#define ERROR_SIM_ERROR        "SIM_ERROR"
#define ERROR_UART_TIMEOUT     "UART_TIMEOUT"

// =========================================
// SYSTEM
// =========================================

#define CMD_GET_SYSTEM_STATE   "GET_SYSTEM_STATE"

#define CMD_CHECK_SYSTEM       "CHECK_SYSTEM"

#define CMD_SMS_RESULT         "SMS_RESULT"

// Contact Sync
#define CMD_SYNC_CONTACT         "SYNC_CONTACT"
#define CMD_DELETE_CONTACT       "DELETE_CONTACT"
#define CMD_SYNC_CONTACTS_CLEAR  "SYNC_CONTACTS_CLEAR"

// Delivery Report
#define CMD_SMS_DELIVERY         "SMS_DELIVERY"

// SOS
#define CMD_SOS                  "SOS_ALERT"

// Audio control
#define CMD_STOP_AUDIO           "STOP_AUDIO"

// =========================================
// PACKET STRUCTURE
// =========================================

struct Packet
{
    String type;
    String command;

    String status;
    String errorCode;

    String packetId;

    String source;
    String target;

    unsigned long timestamp;

    String payload;
};

#endif
