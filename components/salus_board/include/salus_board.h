#pragma once

#include "esp_err.h"
#include "driver/gpio.h"

/* PCB SALUS v3, 506cada, ESP32-S3-WROOM-1-N8R2.
 * GPIO numbers, not module pad numbers. See docs/migration/PINOUT.md. */
enum {
    SALUS_PIN_FC_LEFT = 1, SALUS_PIN_FC_RIGHT = 2,
    SALUS_PIN_AUX_STRAP3 = 3,
    SALUS_PIN_R_PWM = 4, SALUS_PIN_L_PWM = 5, SALUS_PIN_HBRIDGE_EN = 6,
    SALUS_PIN_I2C_SDA = 7, SALUS_PIN_I2C_SCL = 8,
    SALUS_PIN_CS_ACCEL = 9, SALUS_PIN_CS_GYRO = 10,
    SALUS_PIN_SPI_MOSI = 11, SALUS_PIN_SPI_CLOCK = 12, SALUS_PIN_SPI_MISO = 13,
    SALUS_PIN_DR_ACCEL = 14, SALUS_PIN_DR_GYRO = 15, SALUS_PIN_RC_PPM = 16,
    SALUS_PIN_UART1_IO17 = 17, SALUS_PIN_UART1_IO18 = 18,
    SALUS_PIN_USB_DM = 19, SALUS_PIN_USB_DP = 20,
    SALUS_PIN_THROTTLE = 21,
    SALUS_PIN_HALL_A = 35, SALUS_PIN_HALL_B = 36, SALUS_PIN_HALL_C = 37,
    SALUS_PIN_RELAY_LATCH = 38, SALUS_PIN_RELAY_OE = 39,
    SALUS_PIN_SERVO1 = 40, SALUS_PIN_SERVO2 = 41, SALUS_PIN_RS485_DIR = 42,
    SALUS_PIN_DEBUG_TX = 43, SALUS_PIN_DEBUG_RX = 44,
    SALUS_PIN_AUX_STRAP45 = 45, SALUS_PIN_AUX_STRAP46 = 46,
    SALUS_PIN_AUX47 = 47, SALUS_PIN_AUX48 = 48,
    SALUS_PIN_BOOT = 0,
};

/* Bench skeleton only: no actuator drivers, PWM or relay latch writes.
 * Throttle is left as input with pull-down, NOT the calibrated running stop.
 * Does not guarantee safety during reset/power loss or with actuators attached. */
esp_err_t salus_board_init(void);
