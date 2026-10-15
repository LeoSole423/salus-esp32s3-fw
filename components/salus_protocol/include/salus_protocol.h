#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SALUS_COMMAND_SIZE 7
#define SALUS_TELEMETRY_SIZE 8
#define SALUS_FRESH_US 120000ULL
/* Diagnostic request: AB 10 01 00 00 00 CRC, response: 5A + 23 bytes.
 * Only emitted on request; do not use diagnostic extensions with legacy readers. */
#define SALUS_DIAGNOSTIC_SIZE 24

typedef struct {
    uint8_t flags;
    int8_t steer_pct;
    uint16_t speed_centi_mps;
    uint8_t brake_pct;
} salus_command_t;

typedef struct {
    uint8_t pending[SALUS_COMMAND_SIZE];
    size_t used;
    salus_command_t command;
    bool has_command;
    uint64_t last_command_us;
    uint64_t last_byte_us;
    uint32_t accepted, crc_errors, rejected, discarded;
    uint32_t diagnostic_token;
    uint64_t diagnostic_received_us;
} salus_protocol_t;

typedef enum { SALUS_RX_NONE, SALUS_RX_COMMAND, SALUS_RX_DIAGNOSTIC, SALUS_RX_IMU, SALUS_RX_IMU_TIMED } salus_rx_t;

uint8_t salus_crc8(const uint8_t *data, size_t size);
void salus_protocol_reset(salus_protocol_t *state);
/* Called from one owner task, time must be monotonic. Invalid packets never
 * refresh command authority. Partial frames expire after 120 ms. */
salus_rx_t salus_protocol_feed(salus_protocol_t *state, uint8_t byte, uint64_t now_us);
bool salus_protocol_fresh(const salus_protocol_t *state, uint64_t now_us);
/* Returns false and a zeroed command when stale. No actuator authorization. */
bool salus_protocol_command(const salus_protocol_t *state, uint64_t now_us,
                            salus_command_t *command);
/* Skeleton telemetry: NOT READY, FAILSAFE, source NONE, sensors unavailable. */
void salus_protocol_telemetry(const salus_protocol_t *state, uint64_t now_us,
                              uint8_t frame[SALUS_TELEMETRY_SIZE]);
void salus_protocol_diagnostic(const salus_protocol_t *state, uint64_t now_us,
                               uint32_t tx_backpressure, uint8_t frame[SALUS_DIAGNOSTIC_SIZE]);
