#!/usr/bin/env python3
"""Host tests use the real pinned Bosch API with simulated SPI registers."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='salus-imu-') as directory:
    temp = Path(directory)
    bosch = temp / 'bosch'
    subprocess.run([sys.executable, str(root/'tools/fetch_bosch.py'), str(bosch)], check=True)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-g',
                   '-I', str(bosch), '-I', str(root/'components/salus_imu/include'),
                   '-I', str(root/'components/salus_protocol/include'),
                   str(root/'tests/test_imu.c'), str(root/'components/salus_imu/salus_imu_core.c'),
                   str(root/'components/salus_protocol/salus_protocol.c'),
                   *[str(bosch/f) for f in ('bmi08a.c','bmi08g.c','bmi08xa.c')],
                   '-lm', '-o', str(temp/'test')], check=True)
    packet = temp / 'packet.bin'
    subprocess.run([str(temp/'test'), str(packet)], check=True)
    spec = importlib.util.spec_from_file_location('usb_diagnostics', root/'tools/usb_diagnostics.py')
    diagnostics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnostics)
    data = packet.read_bytes()
    decoded = diagnostics.decode_imu(data)
    assert decoded['accel']['raw'][0] == -5460
    assert abs(decoded['accel']['m_s2'][0] + 9.80665) < 0.0001
    assert decoded['accel']['age_us'] == 101 and decoded['gyro']['age_us'] == 1
    assert decoded['accel']['valid'] and decoded['gyro']['valid']
    for invalid in (data[:-1], data[:-1] + bytes([data[-1] ^ 1])):
        try:
            diagnostics.decode_imu(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupt/truncated IMU frame accepted')
    print('C-to-Python IMU packet compatibility passed')

    if len(sys.argv) > 1:
        spec = importlib.util.spec_from_file_location('bmi088_domain_crosscheck', Path(sys.argv[1]))
        codec = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = codec
        spec.loader.exec_module(codec)
        timed = codec.decode(Path(str(packet)+'.timed').read_bytes())
        assert timed.token == 0x123456 and timed.boot_id == 0x1234ABCD
        assert timed.received_us == 190 and timed.capture_us == 201
        assert timed.accel.raw[0] == -5460
        print('Native firmware timed packet decoded by ROS codec: passed')
