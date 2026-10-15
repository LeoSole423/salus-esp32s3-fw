#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "bmi08x.h"

#define SALUS_IMU_FRESH_US 50000ULL
#define SALUS_IMU_MAX_READ_AGE_US 2000ULL
/* All vectors are in the physical Bosch sensor frame, NOT robot ENU/body. */
typedef struct {
    int16_t raw[3];
    float si[3];
    uint64_t timestamp_us; /* host MCU DRDY edge time, not filter-compensated */
    uint32_t sequence;
    bool valid;
    bool saturated;
} salus_imu_vector_t;

int8_t salus_imu_configure(struct bmi08_dev *dev);
void salus_imu_convert(bool gyro, const int16_t raw[3], float si[3]);
bool salus_imu_saturated(const int16_t raw[3]);
bool salus_imu_vector_fresh(const salus_imu_vector_t *v, uint64_t now);

typedef enum { SALUS_IMU_STARTING, SALUS_IMU_RUNNING, SALUS_IMU_FAULT } salus_imu_state_t;
typedef struct {
    salus_imu_state_t state;
    int32_t last_error;
    uint8_t accel_id, gyro_id;
    salus_imu_vector_t accel, gyro;
    int32_t temperature_millic;
    uint64_t temperature_timestamp_us;
    bool temperature_valid;
    uint32_t read_errors, missed_accel, missed_gyro, init_attempts;
} salus_imu_snapshot_t;


#define SALUS_IMU_PACKET_SIZE 112
void salus_imu_encode(const salus_imu_snapshot_t *s, uint64_t now,
                      uint8_t packet[SALUS_IMU_PACKET_SIZE]);

#define SALUS_IMU_TIMED_PACKET_SIZE 128
void salus_imu_encode_timed(const salus_imu_snapshot_t *s, uint64_t now,
    uint64_t request_received_us, uint32_t token, uint32_t boot_id,
    uint8_t packet[SALUS_IMU_TIMED_PACKET_SIZE]);
