#include "salus_imu_core.h"
#include <limits.h>
#include <string.h>
#include "salus_protocol.h"

int8_t salus_imu_configure(struct bmi08_dev *d)
{
    int8_t r;
#define CHECK(call) do { r = (call); if (r != BMI08_OK) return r; } while (0)
    /* API performs the initial dummy transaction and accel SPI dummy bytes. */
    CHECK(bmi08xa_init(d));
    CHECK(bmi08g_init(d));
    CHECK(bmi08a_soft_reset(d));
    CHECK(bmi08g_soft_reset(d));
    d->delay_us(50000, d->intf_ptr_accel);
    CHECK(bmi08xa_init(d));
    CHECK(bmi08g_init(d));
    d->accel_cfg = (struct bmi08_cfg){
        .power = BMI08_ACCEL_PM_ACTIVE, .range = BMI088_ACCEL_RANGE_6G,
        .bw = BMI08_ACCEL_BW_OSR4, .odr = BMI08_ACCEL_ODR_400_HZ,
    };
    d->gyro_cfg = (struct bmi08_cfg){
        .power = BMI08_GYRO_PM_NORMAL, .range = BMI08_GYRO_RANGE_500_DPS,
        .bw = BMI08_GYRO_BW_47_ODR_400_HZ,
        .odr = BMI08_GYRO_BW_47_ODR_400_HZ,
    };
    CHECK(bmi08a_set_power_mode(d));
    CHECK(bmi08g_set_power_mode(d));
    CHECK(bmi08xa_set_meas_conf(d));
    CHECK(bmi08g_set_meas_conf(d));
    CHECK(bmi08a_get_meas_conf(d));
    CHECK(bmi08g_get_meas_conf(d));
    CHECK(bmi08a_get_power_mode(d));
    CHECK(bmi08g_get_power_mode(d));
    struct bmi08_err_reg status = {0};
    CHECK(bmi08a_get_error_status(&status, d));
    if (status.fatal_err || status.err_code) return BMI08_E_INVALID_CONFIG;
    if (d->accel_cfg.power != BMI08_ACCEL_PM_ACTIVE ||
        d->gyro_cfg.power != BMI08_GYRO_PM_NORMAL ||
        d->accel_cfg.range != BMI088_ACCEL_RANGE_6G ||
        d->accel_cfg.bw != BMI08_ACCEL_BW_OSR4 ||
        d->accel_cfg.odr != BMI08_ACCEL_ODR_400_HZ ||
        d->gyro_cfg.range != BMI08_GYRO_RANGE_500_DPS ||
        d->gyro_cfg.bw != BMI08_GYRO_BW_47_ODR_400_HZ)
        return BMI08_E_INVALID_CONFIG;
    struct bmi08_accel_int_channel_cfg accel = {
        .int_channel = BMI08_INT_CHANNEL_1,
        .int_type = BMI08_ACCEL_INT_DATA_RDY,
        .int_pin_cfg = {BMI08_INT_ACTIVE_HIGH, BMI08_INT_MODE_PUSH_PULL, BMI08_ENABLE},
    };
    struct bmi08_gyro_int_channel_cfg gyro = {
        .int_channel = BMI08_INT_CHANNEL_3,
        .int_type = BMI08_GYRO_INT_DATA_RDY,
        .int_pin_cfg = {BMI08_INT_ACTIVE_HIGH, BMI08_INT_MODE_PUSH_PULL, BMI08_ENABLE},
    };
    CHECK(bmi08a_set_int_config(&accel, d));
    CHECK(bmi08g_set_int_config(&gyro, d));
#undef CHECK
    return BMI08_OK;
}

void salus_imu_convert(bool gyro, const int16_t raw[3], float si[3])
{
    /* Bosch nominal sensitivity for +-6g: 5460 LSB/g; +-500dps: 65.536 LSB/dps. */
    const float scale = gyro ? 0.017453292519943295f / 65.536f : 9.80665f / 5460.0f;
    for (unsigned i = 0; i < 3; ++i) si[i] = raw[i] * scale;
}

bool salus_imu_saturated(const int16_t raw[3])
{
    for (unsigned i = 0; i < 3; ++i)
        if (raw[i] == INT16_MIN || raw[i] == INT16_MAX) return true;
    return false;
}

bool salus_imu_vector_fresh(const salus_imu_vector_t *v, uint64_t now)
{
    return v->valid && now >= v->timestamp_us && now - v->timestamp_us <= SALUS_IMU_FRESH_US;
}

/* Explicit LE encoding; no packing or platform struct layout on the wire. */
static void put(uint8_t *p, uint64_t value, unsigned n)
{
    for (unsigned i = 0; i < n; ++i) p[i] = (uint8_t)(value >> (8 * i));
}
static void put_float(uint8_t *p, float value)
{
    _Static_assert(sizeof(float) == 4, "IEEE float32 required");
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    put(p, bits, 4);
}
void salus_imu_encode(const salus_imu_snapshot_t *s, uint64_t now, uint8_t f[112])
{
    memset(f, 0, 112);
    f[0] = 0x5A; f[1] = 0x10; f[2] = 2; f[3] = 112;
    f[4] = (uint8_t)s->state;
    bool running = s->state == SALUS_IMU_RUNNING;
    bool temperature_valid = running && s->temperature_valid &&
        now >= s->temperature_timestamp_us && now - s->temperature_timestamp_us <= 2000000;
    f[5] = (running && salus_imu_vector_fresh(&s->accel, now) ? 1 : 0) |
           (running && salus_imu_vector_fresh(&s->gyro, now) ? 2 : 0) |
           (temperature_valid ? 4 : 0) | (s->accel.saturated ? 8 : 0) |
           (s->gyro.saturated ? 16 : 0);
    f[6] = s->accel_id; f[7] = s->gyro_id;
    put(f+8, (uint32_t)s->last_error, 4);
    put(f+12, s->init_attempts, 4); put(f+16, s->read_errors, 4);
    put(f+20, s->missed_accel, 4); put(f+24, s->missed_gyro, 4);
    put(f+28, s->accel.sequence, 4); put(f+32, s->gyro.sequence, 4);
    put(f+36, s->accel.timestamp_us, 8); put(f+44, s->gyro.timestamp_us, 8);
    put(f+52, s->temperature_timestamp_us, 8);
    for (unsigned i = 0; i < 3; ++i) {
        put(f+60+2*i, (uint16_t)s->accel.raw[i], 2);
        put(f+66+2*i, (uint16_t)s->gyro.raw[i], 2);
        put_float(f+72+4*i, s->accel.si[i]);
        put_float(f+84+4*i, s->gyro.si[i]);
    }
    put(f+96, (uint32_t)s->temperature_millic, 4);
    put(f+100, now, 8); f[108] = 1; /* fixed acquisition profile, not calibrated */
    f[111] = salus_crc8(f, 111);
}

void salus_imu_encode_timed(const salus_imu_snapshot_t *s, uint64_t now,
    uint64_t request_received_us, uint32_t token, uint32_t boot_id, uint8_t f[128])
{
    salus_imu_encode(s, now, f);
    f[2] = 3; f[3] = 128;
    put(f+111, token & 0xFFFFFF, 3);
    put(f+114, boot_id, 4);
    put(f+118, request_received_us, 8);
    f[126] = 0;
    f[127] = salus_crc8(f, 127);
}
