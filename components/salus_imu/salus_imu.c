#include "salus_imu.h"
#include <string.h>
#include "salus_board.h"
#include "driver/spi_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"

static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static salus_imu_snapshot_t published;
static TaskHandle_t owner;
typedef struct { uint64_t time; uint32_t count; } edge_t;
static edge_t edges[2];
static const unsigned accel_index = 0, gyro_index = 1;

static void data_ready(void *arg)
{
    const unsigned index = *(const unsigned *)arg;
    uint64_t now = (uint64_t)esp_timer_get_time();
    portENTER_CRITICAL_ISR(&mux);
    edges[index].time = now;
    ++edges[index].count;
    portEXIT_CRITICAL_ISR(&mux);
    BaseType_t wake = pdFALSE;
    vTaskNotifyGiveFromISR(owner, &wake);
    if (wake) portYIELD_FROM_ISR();
}

static edge_t edge_copy(unsigned index)
{
    portENTER_CRITICAL(&mux);
    edge_t e = edges[index];
    portEXIT_CRITICAL(&mux);
    return e;
}

static void publish(const salus_imu_snapshot_t *s)
{
    portENTER_CRITICAL(&mux);
    published = *s;
    portEXIT_CRITICAL(&mux);
}

void salus_imu_get_snapshot(salus_imu_snapshot_t *out)
{
    portENTER_CRITICAL(&mux);
    *out = published;
    portEXIT_CRITICAL(&mux);
    const uint64_t now = (uint64_t)esp_timer_get_time();
    out->accel.valid = out->state == SALUS_IMU_RUNNING && salus_imu_vector_fresh(&out->accel, now);
    out->gyro.valid = out->state == SALUS_IMU_RUNNING && salus_imu_vector_fresh(&out->gyro, now);
    out->temperature_valid = out->state == SALUS_IMU_RUNNING && out->temperature_valid &&
        now >= out->temperature_timestamp_us && now - out->temperature_timestamp_us <= 2000000;
}

static BMI08_INTF_RET_TYPE bus_read(uint8_t reg, uint8_t *data, uint32_t len, void *ctx)
{
    if (len > 32) return -1;
    uint8_t tx[33] = {0}, rx[33] = {0};
    tx[0] = reg;
    spi_transaction_t t = {.length = (len + 1) * 8, .tx_buffer = tx, .rx_buffer = rx};
    if (spi_device_transmit(*(spi_device_handle_t *)ctx, &t) != ESP_OK) return -1;
    /* The Bosch API itself discards the additional accelerometer dummy byte. */
    memcpy(data, rx + 1, len);
    return 0;
}

static BMI08_INTF_RET_TYPE bus_write(uint8_t reg, const uint8_t *data, uint32_t len, void *ctx)
{
    if (len > 32) return -1;
    uint8_t tx[33]; tx[0] = reg;
    memcpy(tx + 1, data, len);
    spi_transaction_t t = {.length = (len + 1) * 8, .tx_buffer = tx};
    return spi_device_transmit(*(spi_device_handle_t *)ctx, &t) == ESP_OK ? 0 : -1;
}

static void delay_us(uint32_t us, void *ctx)
{
    (void)ctx;
    /* Never shorten mandatory Bosch delays due to tick rounding. */
    if (us >= 2000) vTaskDelay(pdMS_TO_TICKS((us + 999) / 1000));
    else esp_rom_delay_us(us);
}

static esp_err_t setup_bus(spi_device_handle_t handles[2])
{
    spi_bus_config_t cfg = {
        .mosi_io_num = SALUS_PIN_SPI_MOSI, .miso_io_num = SALUS_PIN_SPI_MISO,
        .sclk_io_num = SALUS_PIN_SPI_CLOCK, .quadwp_io_num = -1, .quadhd_io_num = -1,
        .max_transfer_sz = 33,
    };
    esp_err_t e = spi_bus_initialize(SPI2_HOST, &cfg, SPI_DMA_DISABLED);
    if (e != ESP_OK) return e;
    for (unsigned i = 0; i < 2; ++i) {
        spi_device_interface_config_t device = {
            .clock_speed_hz = 4000000, .mode = 0, .queue_size = 1,
            .spics_io_num = i ? SALUS_PIN_CS_GYRO : SALUS_PIN_CS_ACCEL,
        };
        e = spi_bus_add_device(SPI2_HOST, &device, &handles[i]);
        if (e != ESP_OK) return e;
    }
    gpio_config_t drdy = {
        .pin_bit_mask = (1ULL << SALUS_PIN_DR_ACCEL) | (1ULL << SALUS_PIN_DR_GYRO),
        .mode = GPIO_MODE_INPUT, .intr_type = GPIO_INTR_POSEDGE,
        .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_ENABLE,
    };
    e = gpio_config(&drdy);
    if (e != ESP_OK) return e;
    e = gpio_install_isr_service(0);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) return e;
    e = gpio_isr_handler_add(SALUS_PIN_DR_ACCEL, data_ready, (void *)&accel_index);
    if (e != ESP_OK) return e;
    return gpio_isr_handler_add(SALUS_PIN_DR_GYRO, data_ready, (void *)&gyro_index);
}

static void imu_task(void *arg)
{
    (void)arg;
    salus_imu_snapshot_t s = { .state = SALUS_IMU_STARTING };
    spi_device_handle_t handles[2] = {0};
    esp_err_t bus_error = setup_bus(handles);
    if (bus_error != ESP_OK) {
        s.state = SALUS_IMU_FAULT; s.last_error = bus_error; publish(&s);
        /* Resource setup failure requires restart; don't repeatedly allocate. */
        vTaskSuspend(NULL);
    }
    struct bmi08_dev dev = {
        .intf = BMI08_SPI_INTF, .variant = BMI088_VARIANT,
        .intf_ptr_accel = &handles[0], .intf_ptr_gyro = &handles[1],
        .read = bus_read, .write = bus_write, .delay_us = delay_us,
        .read_write_len = 32,
    };
    for (;;) {
        ++s.init_attempts;
        s.state = SALUS_IMU_STARTING;
        s.accel.valid = s.gyro.valid = s.temperature_valid = false;
        publish(&s);
        int8_t r = salus_imu_configure(&dev);
        s.accel_id = dev.accel_chip_id; s.gyro_id = dev.gyro_chip_id;
        if (r != BMI08_OK) {
            s.state = SALUS_IMU_FAULT; s.last_error = r; publish(&s);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        s.state = SALUS_IMU_RUNNING; s.last_error = 0;
        uint32_t consumed[2] = {edge_copy(0).count, edge_copy(1).count};
        const uint64_t started = (uint64_t)esp_timer_get_time();
        uint64_t next_temperature = 0;
        unsigned consecutive_errors = 0;
        publish(&s);
        while (s.state == SALUS_IMU_RUNNING) {
            ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10));
            for (unsigned i = 0; i < 2; ++i) {
                edge_t before = edge_copy(i);
                uint32_t count = before.count - consumed[i];
                if (!count) continue;
                consumed[i] = before.count;
                uint32_t *missed = i ? &s.missed_gyro : &s.missed_accel;
                *missed += count - 1;
                salus_imu_vector_t *v = i ? &s.gyro : &s.accel;
                uint64_t now = (uint64_t)esp_timer_get_time();
                if (now < before.time || now - before.time > SALUS_IMU_MAX_READ_AGE_US) {
                    ++*missed; continue;
                }
                struct bmi08_sensor_data data;
                r = i ? bmi08g_get_data(&data, &dev) : bmi08a_get_data(&data, &dev);
                if (r != BMI08_OK) {
                    ++s.read_errors; ++consecutive_errors;
                    s.last_error = r; v->valid = false;
                    if (consecutive_errors >= 3) s.state = SALUS_IMU_FAULT;
                    continue;
                }
                edge_t after = edge_copy(i);
                now = (uint64_t)esp_timer_get_time();
                if (after.count != before.count || now - before.time > SALUS_IMU_MAX_READ_AGE_US) {
                    ++*missed; continue; /* Registers may belong to a newer edge. */
                }
                consecutive_errors = 0;
                v->raw[0] = data.x; v->raw[1] = data.y; v->raw[2] = data.z;
                salus_imu_convert(i != 0, v->raw, v->si);
                v->timestamp_us = before.time; ++v->sequence;
                v->saturated = salus_imu_saturated(v->raw); v->valid = true;
            }
            uint64_t now = (uint64_t)esp_timer_get_time();
            if (now >= next_temperature) {
                int32_t temperature;
                r = bmi08a_get_sensor_temperature(&dev, &temperature);
                s.temperature_valid = r == BMI08_OK && temperature != -105000;
                if (s.temperature_valid) {
                    s.temperature_millic = temperature; s.temperature_timestamp_us = now;
                } else ++s.read_errors;
                next_temperature = now + 1000000;
            }
            if (now - started > 100000 &&
                (!salus_imu_vector_fresh(&s.accel, now) || !salus_imu_vector_fresh(&s.gyro, now))) {
                s.state = SALUS_IMU_FAULT; s.last_error = ESP_ERR_TIMEOUT;
            }
            publish(&s);
        }
        s.accel.valid = s.gyro.valid = s.temperature_valid = false;
        publish(&s);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

esp_err_t salus_imu_start(void)
{
    if (owner) return ESP_ERR_INVALID_STATE;
    return xTaskCreate(imu_task, "salus_imu", 4096, NULL, 5, &owner) == pdPASS
        ? ESP_OK : ESP_ERR_NO_MEM;
}
