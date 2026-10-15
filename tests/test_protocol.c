#include "salus_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static salus_rx_t feed(salus_protocol_t *s, uint8_t *f, size_t n, uint64_t now)
{
    salus_rx_t result = SALUS_RX_NONE;
    for (size_t i = 0; i < n; ++i) {
        salus_rx_t r = salus_protocol_feed(s, f[i], now);
        if (r) result = r;
    }
    return result;
}
int main(void)
{
    salus_protocol_t s;
    salus_protocol_reset(&s);
    salus_command_t cmd;
    assert(!salus_protocol_command(&s, 0, &cmd));
    uint8_t f[] = {0xAA,0x26,0x9C,0x78,0,15,0};
    f[6] = salus_crc8(f, 6);
    assert(feed(&s, f, 3, 1) == SALUS_RX_NONE);
    assert(feed(&s, f+3, 4, 100) == SALUS_RX_COMMAND);
    assert(s.command.steer_pct == -100 && s.command.speed_centi_mps == 120);
    assert(s.command.flags == 6 && s.command.brake_pct == 15);
    assert(salus_protocol_fresh(&s, 120100));
    assert(!salus_protocol_fresh(&s, 120101));
    assert(!salus_protocol_command(&s, 120101, &cmd));
    assert(cmd.flags == 0 && cmd.speed_centi_mps == 0);
    uint8_t bad[7]; memcpy(bad,f,7); bad[6]^=1;
    assert(feed(&s,bad,7,200000) == SALUS_RX_NONE);
    assert(s.last_command_us == 100 && s.crc_errors == 1);
    memcpy(bad,f,7); bad[1]=0x32; bad[6]=salus_crc8(bad,6);
    assert(feed(&s,bad,7,200001) == SALUS_RX_NONE && s.rejected == 1);
    assert(s.last_command_us == 100);
    /* Embedded valid header after noise/corrupt candidate. */
    uint8_t noise[] = {0x13,0xAA,0x22};
    feed(&s,noise,sizeof(noise),300000);
    assert(feed(&s,f,7,300001) == SALUS_RX_COMMAND);
    assert(s.accepted == 2);
    /* Partial frame must not survive expiry. */
    salus_protocol_reset(&s);
    feed(&s,f,3,0);
    assert(feed(&s,f+3,4,120001) == SALUS_RX_NONE && !s.has_command);
    assert(feed(&s,f,7,120002) == SALUS_RX_COMMAND);
    assert(feed(&s,f,7,120003) == SALUS_RX_COMMAND);
    uint8_t telemetry[8];
    salus_protocol_telemetry(&s,120003,telemetry);
    assert(telemetry[1] == 0x0C && telemetry[2] == 255 && telemetry[3] == 255);
    assert(telemetry[4] == 0 && telemetry[5] == 0x80 && telemetry[6] == 0);
    assert(telemetry[7] == salus_crc8(telemetry,7));
    salus_protocol_telemetry(&s,240004,telemetry);
    assert(telemetry[1] == 4);
    uint8_t diag[] = {0xAB,0x10,1,0,0,0,0};
    diag[6]=salus_crc8(diag,6);
    uint64_t stamp = s.last_command_us;
    assert(feed(&s,diag,7,300000) == SALUS_RX_DIAGNOSTIC);
    assert(s.last_command_us == stamp && !salus_protocol_fresh(&s,300000));
    diag[2] = 2; diag[6] = salus_crc8(diag,6);
    assert(feed(&s,diag,7,300001) == SALUS_RX_IMU);
    assert(s.last_command_us == stamp);
    diag[2] = 3; diag[3] = 0x56; diag[4] = 0x34; diag[5] = 0x12;
    diag[6] = salus_crc8(diag,6);
    assert(feed(&s,diag,7,300002) == SALUS_RX_IMU_TIMED);
    assert(s.diagnostic_token == 0x123456 && s.diagnostic_received_us == 300002);
    diag[2] = 4; diag[6] = salus_crc8(diag,6);
    assert(feed(&s,diag,7,300003) == SALUS_RX_NONE);
    assert(s.last_command_us == stamp);
    uint8_t response[24]; salus_protocol_diagnostic(&s,300000,10,response);
    assert(response[0] == 0x5A && response[3] == 24 && response[16] == 10);
    assert(response[23] == salus_crc8(response,23));
    f[1]=0x21; f[6]=salus_crc8(f,6);
    feed(&s,f,7,400000); salus_protocol_telemetry(&s,400000,telemetry);
    assert(telemetry[1] == 0x0E);
    salus_protocol_reset(&s);
    assert(!salus_protocol_fresh(&s,400000));
    puts("protocol tests passed");
}
