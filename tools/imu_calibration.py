#!/usr/bin/env python3
"""Explicit host calibration for BMI088; never writes sensor registers or actuator commands."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from salus_imu_calibration.domain import (
    POSES, identity, summarize, calibrate_gyro, calibrate_accel, apply_profile, sensor_check,
)
from salus_imu_calibration.storage import load_json, save_new


def capture(link, device_id, pose, duration, read_snapshot, clock=time.monotonic, sleep=time.sleep):
    identity(device_id)
    if not 10 <= duration <= 120:
        raise ValueError('Capture duration must be 10..120 seconds')
    if pose not in (*POSES, 'stationary'):
        raise ValueError('Unsupported pose')
    result = dict(schema_version=1, kind='salus_bmi088_capture',
                  device_id=device_id, pose=pose, requested_duration_s=duration,
                  created_utc=datetime.now(timezone.utc).isoformat(), samples=[])
    deadline = clock()+duration
    previous = None
    while clock() < deadline:
        started = clock()
        sample = read_snapshot(link)
        sensor_check(sample)
        for key in ('accel', 'gyro'):
            if sample[key]['valid'] is not True or sample[key]['saturated']:
                raise ValueError('Invalid or saturated IMU data during capture')
        if previous is not None:
            for key in ('accel', 'gyro'):
                if (sample[key]['sequence'] < previous[key]['sequence'] or
                        sample[key]['timestamp_us'] < previous[key]['timestamp_us']):
                    raise ValueError('IMU counter/clock reset during capture')
            if sample['init_attempts'] != previous['init_attempts']:
                raise ValueError('IMU reinitialized during capture')
        if previous is None or all(sample[k]['sequence'] != previous[k]['sequence'] for k in ('accel', 'gyro')):
            result['samples'].append(sample)
            previous = sample
        sleep(max(0, 0.02-(clock()-started)))
    summarize(result)  # No successful output file if quality checks fail.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    collect = sub.add_parser('capture', help='Record an explicitly stationary board/vehicle')
    collect.add_argument('port')
    collect.add_argument('--device-id', required=True, help='Unique physical board label/serial; record it on the PCB')
    collect.add_argument('--pose', choices=(*POSES, 'stationary'), default='stationary')
    collect.add_argument('--duration', type=float, default=10)
    collect.add_argument('--warmup', type=float, default=60, help='Seconds to wait before recording (default 60)')
    collect.add_argument('--output', required=True)
    gyro = sub.add_parser('gyro', help='Calculate stationary gyro bias; preserve existing accel calibration')
    gyro.add_argument('--capture', required=True)
    gyro.add_argument('--base', help='Existing profile to retain accelerometer calibration')
    gyro.add_argument('--output', required=True)
    accel = sub.add_parser('accel', help='Calculate accelerometer offsets/scales from six stationary poses')
    accel.add_argument('--captures', nargs=6, required=True)
    accel.add_argument('--base', help='Existing profile to retain gyro calibration')
    accel.add_argument('--output', required=True)
    apply = sub.add_parser('apply', help='Apply a profile to a snapshot JSON offline')
    apply.add_argument('--profile', required=True)
    apply.add_argument('--snapshot', required=True)
    apply.add_argument('--device-id', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'apply':
            result = apply_profile(load_json(args.snapshot), load_json(args.profile), args.device_id)
            print(json.dumps(result, indent=2, allow_nan=False))
            return
        if Path(args.output).exists():
            raise ValueError('Output already exists; choose a new filename to preserve the previous calibration')
        if args.command == 'capture':
            if not 0 <= args.warmup <= 600 or not 10 <= args.duration <= 120:
                raise ValueError('warmup must be 0..600 s; duration must be 10..120 s')
            identity(args.device_id)
            from usb_diagnostics import read_diagnostic, decode_imu
            import serial
            print('Keep the board/vehicle stationary. Do not run another serial consumer.', file=sys.stderr)
            with serial.Serial(args.port, 115200, timeout=0.05, write_timeout=1, exclusive=True) as link:
                print(f'Warmup wait: {args.warmup:g} s', file=sys.stderr)
                time.sleep(args.warmup)
                result = capture(link, args.device_id, args.pose, args.duration,
                                 lambda port: decode_imu(read_diagnostic(port, 2)))
        else:
            base = load_json(args.base) if args.base else None
            result = (calibrate_gyro(load_json(args.capture), base) if args.command == 'gyro' else
                      calibrate_accel([load_json(p) for p in args.captures], base))
        save_new(args.output, result)
        print(f'Saved: {args.output}')
    except (ValueError, OSError, TimeoutError, KeyError, TypeError) as error:
        parser.exit(2, f'Calibration failed: {error}\n')


if __name__ == '__main__':
    main()
