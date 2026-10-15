#include "salus_imu_core.h"
#include "salus_protocol.h"
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    bool gyro, fail, ignore_config;
    uint8_t registers[128];
    unsigned dummy_reads;
} chip_t;
static chip_t chips[2];
static uint64_t delays;
static BMI08_INTF_RET_TYPE read_reg(uint8_t reg, uint8_t *p, uint32_t n, void *ctx)
{
    chip_t *c = ctx;
    if (c->fail) return -1;
    assert(reg & 0x80); /* API must set SPI read bit */
    reg &= 0x7F;
    unsigned dummy = c->gyro ? 0 : 1;
    if (dummy) { p[0] = 0xAD; ++c->dummy_reads; }
    assert(n >= dummy && reg + n - dummy <= 128);
    for (unsigned i = dummy; i < n; ++i) p[i] = c->registers[reg + i - dummy];
    return 0;
}
static BMI08_INTF_RET_TYPE write_reg(uint8_t reg, const uint8_t *p, uint32_t n, void *ctx)
{
    chip_t *c = ctx;
    if (c->fail) return -1;
    assert(!(reg & 0x80));
    if (c->ignore_config && reg == 0x40) return 0;
    assert(reg + n <= 128);
    memcpy(c->registers + reg, p, n);
    return 0;
}
static void delay(uint32_t us, void *ctx) { (void)ctx; delays += us; }
static struct bmi08_dev device(void)
{
    memset(chips, 0, sizeof(chips));
    chips[0].registers[0] = 0x1E;
    chips[1].registers[0] = 0x0F; chips[1].gyro = true;
    return (struct bmi08_dev){
        .intf = BMI08_SPI_INTF, .variant = BMI088_VARIANT,
        .intf_ptr_accel = &chips[0], .intf_ptr_gyro = &chips[1],
        .read = read_reg, .write = write_reg, .delay_us = delay, .read_write_len = 32,
    };
}
int main(int argc, char **argv)
{
    struct bmi08_dev d = device();
    assert(salus_imu_configure(&d) == BMI08_OK);
    assert(d.accel_chip_id == 0x1E && d.gyro_chip_id == 0x0F && chips[0].dummy_reads >= 4);
    assert(chips[0].registers[0x40] == 0x8A && chips[0].registers[0x41] == 1);
    assert((chips[1].registers[0x10] & 7) == 3 && chips[1].registers[0x0F] == 2);
    assert(chips[0].registers[0x7D] == 4 && delays >= 50000);
    assert(chips[0].registers[0x58] & 4); /* accel data ready mapped INT1 */
    assert(chips[1].registers[0x18] & 1); /* gyro data ready mapped INT3 */
    /* Actual Bosch burst read must discard dummy and decode signed LE. */
    uint8_t acc[] = {0x54,0x15,0xAC,0xEA,0,0}; /* +5460, -5460, 0 */
    memcpy(chips[0].registers+0x12,acc,6);
    struct bmi08_sensor_data raw;
    assert(bmi08a_get_data(&raw,&d) == BMI08_OK);
    assert(raw.x == 5460 && raw.y == -5460 && raw.z == 0);
    int16_t a[] = {raw.x,raw.y,raw.z}; float si[3];
    salus_imu_convert(false,a,si);
    assert(fabsf(si[0]-9.80665f)<0.0001f && fabsf(si[1]+9.80665f)<0.0001f);
    int16_t g[] = {16384,-16384,0}; salus_imu_convert(true,g,si);
    assert(fabsf(si[0]-4.36332313f)<0.0001f && si[1]<0);
    assert(!salus_imu_saturated(g)); g[0]=INT16_MIN; assert(salus_imu_saturated(g));
    salus_imu_snapshot_t s = {.state=SALUS_IMU_RUNNING,.accel_id=0x1E,.gyro_id=0x0F};
    s.accel.valid=true; s.accel.timestamp_us=100; s.accel.raw[0]=-5460;
    s.gyro.valid=true; s.gyro.timestamp_us=200;
    assert(salus_imu_vector_fresh(&s.accel,50100));
    assert(!salus_imu_vector_fresh(&s.accel,50101));
    assert(!salus_imu_vector_fresh(&s.accel,99));
    uint8_t f[112]; salus_imu_encode(&s,201,f);
    assert(f[2]==2 && f[3]==112 && f[5]==3 && f[36]==100 && f[44]==200);
    assert(f[60]==0xAC && f[61]==0xEA && f[111]==salus_crc8(f,111));
    salus_imu_encode(&s,50101,f); assert(f[5]==2); /* separate ages */
    s.state=SALUS_IMU_FAULT; salus_imu_encode(&s,201,f); assert(f[5]==0);
    d=device(); chips[0].registers[0]=0; assert(salus_imu_configure(&d)!=BMI08_OK);
    d=device(); chips[1].registers[0]=0; assert(salus_imu_configure(&d)!=BMI08_OK);
    d=device(); chips[0].fail=true; assert(salus_imu_configure(&d)!=BMI08_OK);
    d=device(); chips[0].ignore_config=true; assert(salus_imu_configure(&d)!=BMI08_OK);
    uint8_t timed[128];
    salus_imu_encode_timed(&s, 201, 190, 0x123456, 0x1234ABCD, timed);
    assert(timed[2] == 3 && timed[3] == 128 && timed[111] == 0x56);
    assert(timed[114] == 0xCD && timed[118] == 190 && timed[127] == salus_crc8(timed,127));
    if (argc == 2) {
        s.state = SALUS_IMU_RUNNING;
        salus_imu_convert(false, s.accel.raw, s.accel.si);
        salus_imu_encode(&s, 201, f);
        FILE *output = fopen(argv[1], "wb"); assert(output);
        assert(fwrite(f, 1, sizeof(f), output) == sizeof(f)); fclose(output);
        salus_imu_encode_timed(&s, 201, 190, 0x123456, 0x1234ABCD, timed);
        char path[1024]; snprintf(path, sizeof(path), "%s.timed", argv[1]);
        output = fopen(path, "wb"); assert(output);
        assert(fwrite(timed, 1, sizeof(timed), output) == sizeof(timed)); fclose(output);
    }
    puts("IMU tests passed: Bosch SPI, config/readback, signed data, SI, freshness, diagnostic, faults");
}
