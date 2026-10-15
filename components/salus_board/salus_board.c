#include "salus_board.h"
#include "sdkconfig.h"

#if !CONFIG_IDF_TARGET_ESP32S3
#error "SALUS PCB v3 requires ESP32-S3"
#endif

static esp_err_t output(gpio_num_t pin, int level)
{
    /* Preload the output latch before enabling the output driver. */
    esp_err_t err = gpio_set_level(pin, level);
    if (err != ESP_OK) return err;
    return gpio_set_direction(pin, GPIO_MODE_OUTPUT);
}

esp_err_t salus_board_init(void)
{
    /* OE is active low: never enable unknown shift-register contents. */
    esp_err_t err = output(SALUS_PIN_RELAY_OE, 1);
    if (err != ESP_OK) return err;
    const gpio_num_t low_outputs[] = {
        SALUS_PIN_HBRIDGE_EN, SALUS_PIN_R_PWM, SALUS_PIN_L_PWM,
        SALUS_PIN_RELAY_LATCH, SALUS_PIN_SERVO1, SALUS_PIN_SERVO2,
        SALUS_PIN_RS485_DIR,
    };
    for (unsigned i = 0; i < sizeof(low_outputs) / sizeof(low_outputs[0]); ++i) {
        err = output(low_outputs[i], 0);
        if (err != ESP_OK) return err;
    }
    err = output(SALUS_PIN_CS_ACCEL, 1);
    if (err != ESP_OK) return err;
    err = output(SALUS_PIN_CS_GYRO, 1);
    if (err != ESP_OK) return err;
    const gpio_config_t throttle = {
        .pin_bit_mask = 1ULL << SALUS_PIN_THROTTLE,
        .mode = GPIO_MODE_INPUT,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    /* USB pins, strapping pins and unimplemented sensor buses are untouched. */
    return gpio_config(&throttle);
}
