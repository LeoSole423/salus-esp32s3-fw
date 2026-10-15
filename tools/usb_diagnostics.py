#!/usr/bin/env python3
"""Read-only diagnostics; requires pyserial and exclusive access to the S3 port."""
import argparse
import json
import struct
import time


def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ (0x31 if crc & 0x80 else 0)) & 255
    return crc


def decode_imu(frame):
    if len(frame) != 112 or frame[:4] != bytes([0x5A, 0x10, 2, 112]) or crc8(frame[:-1]) != frame[-1]:
        raise ValueError('Invalid IMU diagnostic frame')
    flags = frame[5]
    now = struct.unpack_from('<Q', frame, 100)[0]
    accel_time, gyro_time, temp_time = struct.unpack_from('<QQQ', frame, 36)
    return {
        'state': {0: 'starting', 1: 'running', 2: 'fault'}.get(frame[4], 'unknown'),
        'last_error': struct.unpack_from('<i', frame, 8)[0],
        'chip_ids': list(frame[6:8]), 'profile': frame[108],
        'calibrated': False, 'frame': 'bosch_sensor',
        'hardware_synchronized': False, 'timestamp_basis': 'MCU_DRDY_no_filter_compensation',
        'init_attempts': struct.unpack_from('<I', frame, 12)[0],
        'read_errors': struct.unpack_from('<I', frame, 16)[0],
        'missed_accel': struct.unpack_from('<I', frame, 20)[0],
        'missed_gyro': struct.unpack_from('<I', frame, 24)[0],
        'accel': {'valid': bool(flags & 1), 'saturated': bool(flags & 8),
            'sequence': struct.unpack_from('<I', frame, 28)[0],
            'timestamp_us': accel_time, 'age_us': now-accel_time if accel_time <= now else None,
            'raw': struct.unpack_from('<hhh', frame, 60),
            'm_s2': struct.unpack_from('<fff', frame, 72)},
        'gyro': {'valid': bool(flags & 2), 'saturated': bool(flags & 16),
            'sequence': struct.unpack_from('<I', frame, 32)[0],
            'timestamp_us': gyro_time, 'age_us': now-gyro_time if gyro_time <= now else None,
            'raw': struct.unpack_from('<hhh', frame, 66),
            'rad_s': struct.unpack_from('<fff', frame, 84)},
        'temperature': {'valid': bool(flags & 4), 'timestamp_us': temp_time,
            'celsius': struct.unpack_from('<i', frame, 96)[0] / 1000.0},
    }


def read_diagnostic(link, opcode, timeout=3.0):
    """Request a snapshot, ignoring telemetry and recovering after bad CRC/noise."""
    request = bytes([0xAB, 0x10, opcode, 0, 0, 0])
    link.reset_input_buffer()
    if link.write(request + bytes([crc8(request)])) != 7:
        raise IOError('Partial diagnostic request write')
    buffer = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        buffer.extend(link.read(min(max(getattr(link, 'in_waiting', 0), 1), 256)))
        while buffer:
            size = 8 if buffer[0] == 0x55 else None
            if buffer[0] == 0x5A:
                if len(buffer) < 4:
                    break
                if buffer[1:4] == bytes([0x10, 1, 24]): size = 24
                elif buffer[1:4] == bytes([0x10, 2, 112]): size = 112
            if size is None:
                del buffer[0]
                continue
            if len(buffer) < size:
                break
            frame = bytes(buffer[:size])
            if crc8(frame[:-1]) != frame[-1]:
                del buffer[0]
                continue
            del buffer[:size]
            if frame[0] == 0x5A and frame[2] == opcode:
                return frame
    raise TimeoutError('No diagnostic response within timeout')


def main():
    import serial
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', help='Stable S3 device path, not a GNSS/BMS port')
    parser.add_argument('--imu', action='store_true', help='Read the latest BMI088 snapshot')
    parser.add_argument('--calibration', help='Apply a saved JSON profile on the host; requires --imu')
    parser.add_argument('--device-id', help='Physical board label/serial used when calibrating')
    args = parser.parse_args()
    profile = None
    if args.calibration:
        if not args.imu or not args.device_id:
            parser.error('--calibration requires --imu and --device-id')
        from salus_imu_calibration.storage import load_json
        from salus_imu_calibration.domain import validate_profile
        profile = load_json(args.calibration)
        validate_profile(profile, args.device_id)
    with serial.Serial(args.port, 115200, timeout=0.05, write_timeout=1,
                       exclusive=True) as link:
        frame = read_diagnostic(link, 2 if args.imu else 1)
        if args.imu:
            result = decode_imu(frame)
            if profile is not None:
                from salus_imu_calibration.domain import apply_profile
                result = apply_profile(result, profile, args.device_id)
            print(json.dumps(result, indent=2, allow_nan=False))
        else:
            counts = struct.unpack_from('<IIII', frame, 4)
            print(json.dumps(dict(zip(
                ('commands', 'crc_errors', 'rejected', 'tx_backpressure'), counts)), indent=2))
            print('command_fresh:', bool(frame[20]))


if __name__ == '__main__':
    main()
