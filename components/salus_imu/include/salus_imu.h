#pragma once
#include "esp_err.h"
#include "salus_imu_core.h"

/* Nonblocking start. Initialization/retry runs independently from USB.
 * SPI2 belongs to this component in this delivery; future relays must share
 * the bus through a single arbiter, never toggle CLOCK/MOSI directly. */
esp_err_t salus_imu_start(void);
void salus_imu_get_snapshot(salus_imu_snapshot_t *out);
