#ifndef SYSTEM_STATE_H
#define SYSTEM_STATE_H

#include <Arduino.h>
#include "config.h"
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/queue.h>

// ============================================
// INPUT STATE
// ============================================

enum InputState
{
    INPUT_IDLE,
    INPUT_CONTACT_ID,
    INPUT_CONTACT_PHONE
};

// ============================================
// SYSTEM STATE
// ============================================

struct SystemState
{
    bool uartConnected = false;
    bool simReady      = false;
    bool simInserted   = false;
    bool networkReady  = false;
    bool smsReady      = false;
    int  signalStrength = 0;

    bool lcdPopupActive   = false;
    String lcdLine1       = "AI SYSTEM";
    String lcdLine2       = "STARTING...";
    unsigned long lcdPopupStart = 0;

    InputState inputState        = INPUT_IDLE;
    String currentContactId      = "";
    String currentContactPhone   = "";
    String lastSMSPhone          = "";
    String lastSMSMessage        = "";
    unsigned long lastHeartbeatTime = 0;
};

struct SMSJob
{
    char packetId[48];
    char phone[MAX_PHONE_LENGTH + 1];
    char message[MAX_MESSAGE_LENGTH + 1];
    int  priority;
    char category[32];
};

// ============================================
// GLOBAL STATE (defined in system_manager.cpp)
// ============================================

extern SystemState systemState;
extern QueueHandle_t smsQueue;
extern bool sendingSMS;
extern SemaphoreHandle_t simMutex;
extern SemaphoreHandle_t lcdMutex;

#endif
