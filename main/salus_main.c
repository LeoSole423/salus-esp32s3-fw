#include <stddef.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/usb_serial_jtag.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_log.h"
#include "salus_board.h"
#include "salus_protocol.h"
#include "salus_imu.h"

#if CONFIG_FREERTOS_HZ < 1000
#error "USB transport requires a 1 ms FreeRTOS tick"
#endif

/* Dedicated USB owner; no printf/console/second serial reader. */
static int discard_log(const char *format, va_list args)
{
    (void)format; (void)args;
    return 0;
}

void app_main(void)
{
    esp_log_set_vprintf(discard_log);
    ESP_ERROR_CHECK(salus_board_init());
    usb_serial_jtag_driver_config_t config = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
    ESP_ERROR_CHECK(salus_imu_start());
    salus_protocol_t protocol;
    salus_protocol_reset(&protocol);
    uint32_t tx_backpressure = 0;
    uint64_t next_telemetry = 0;
    bool was_connected = false;
    const uint32_t boot_id = esp_random();
    uint8_t tx[SALUS_IMU_TIMED_PACKET_SIZE];
    uint32_t pending_token = 0;
    uint64_t pending_received_us = 0;
    size_t tx_size = 0, tx_offset = 0;
    salus_rx_t diagnostic_pending = SALUS_RX_NONE;
    for (;;) {
        const bool connected = usb_serial_jtag_is_connected();
        if (connected != was_connected) {
            /* SOF detection is physical USB presence, not an application session.
             * Reset driver buffers on cable transitions to discard queued commands. */
            ESP_ERROR_CHECK(usb_serial_jtag_driver_uninstall());
            ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
            salus_protocol_reset(&protocol);
            tx_size = tx_offset = 0;
            diagnostic_pending = SALUS_RX_NONE;
            was_connected = connected;
        }
        uint8_t rx[64];
        int n = usb_serial_jtag_read_bytes(rx, sizeof(rx), 0);
        uint64_t now = (uint64_t)esp_timer_get_time();
        if (connected) {
            for (int i = 0; i < n; ++i) {
                salus_rx_t result = salus_protocol_feed(&protocol, rx[i], (uint64_t)esp_timer_get_time());
                if (result == SALUS_RX_DIAGNOSTIC || result == SALUS_RX_IMU || result == SALUS_RX_IMU_TIMED) {
                    diagnostic_pending = result;
                    pending_token = protocol.diagnostic_token;
                    pending_received_us = protocol.diagnostic_received_us;
                }
            }
        }
        /* Feed stamps are captured at packet completion, after loop entry. */
        now = (uint64_t)esp_timer_get_time();
        /* Finish a partial write before selecting another frame. Bounded queue,
         * no waiting for host, no retry loop that blocks command reception. */
        if (connected && tx_size == 0) {
            if (now >= next_telemetry) {
                salus_protocol_telemetry(&protocol, now, tx);
                tx_size = SALUS_TELEMETRY_SIZE;
                next_telemetry = now + 10000;
            } else if (diagnostic_pending) {
                if (diagnostic_pending == SALUS_RX_IMU || diagnostic_pending == SALUS_RX_IMU_TIMED) {
                    salus_imu_snapshot_t snapshot;
                    salus_imu_get_snapshot(&snapshot);
                    if (diagnostic_pending == SALUS_RX_IMU_TIMED) {
                        salus_imu_encode_timed(&snapshot, (uint64_t)esp_timer_get_time(),
                            pending_received_us, pending_token, boot_id, tx);
                        tx_size = SALUS_IMU_TIMED_PACKET_SIZE;
                    } else {
                        salus_imu_encode(&snapshot, (uint64_t)esp_timer_get_time(), tx);
                        tx_size = SALUS_IMU_PACKET_SIZE;
                    }
                } else {
                    salus_protocol_diagnostic(&protocol, now, tx_backpressure, tx);
                    tx_size = SALUS_DIAGNOSTIC_SIZE;
                }
                diagnostic_pending = SALUS_RX_NONE;
            }
        }
        if (connected && tx_size) {
            int written = usb_serial_jtag_write_bytes(tx + tx_offset, tx_size - tx_offset, 0);
            if (written > 0) tx_offset += (size_t)written;
            else ++tx_backpressure; /* counts backpressure attempts, not complete lost frames */
            if (tx_offset == tx_size) tx_size = tx_offset = 0;
        }
        /* No control outputs: fresh DRIVE_EN is data, never authorization here. */
        vTaskDelay(1);
    }
}
