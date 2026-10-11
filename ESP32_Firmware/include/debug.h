#ifndef DEBUG_H
#define DEBUG_H

#include <Arduino.h>
#include "config.h"

#if ENABLE_DEBUG

#define DEBUG_PRINT(x) Serial.print(x)
#define DEBUG_PRINTLN(x) Serial.println(x)

#else

#define DEBUG_PRINT(x)
#define DEBUG_PRINTLN(x)

#endif

#endif