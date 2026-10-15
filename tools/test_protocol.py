#!/usr/bin/env python3
"""Compile pure C tests, then cross-check CRC with the actual Jetson codec."""
import ctypes
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import types

root = pathlib.Path(__file__).resolve().parents[1]
source = root / 'components/salus_protocol/salus_protocol.c'
include = source.parent / 'include'
with tempfile.TemporaryDirectory(prefix='salus-protocol-') as directory:
    temp = pathlib.Path(directory)
    common = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(include)]
    subprocess.run(common + ['-fsanitize=address,undefined', str(source),
                   str(root / 'tests/test_protocol.c'), '-o', str(temp/'test')], check=True)
    subprocess.run([str(temp/'test')], check=True)
    subprocess.run(common + ['-shared', '-fPIC', str(source), '-o', str(temp/'codec.so')], check=True)
    lib = ctypes.CDLL(str(temp/'codec.so'))
    lib.salus_crc8.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.salus_crc8.restype = ctypes.c_uint8
    if len(sys.argv) != 2:
        raise SystemExit('Usage: tools/test_protocol.py PATH_TO_JETSON_rpy_esp32_comms')
    package = pathlib.Path(sys.argv[1]).resolve()
    # Load domain modules without importing ROS/serial transport via __init__.
    namespace = types.ModuleType('jetson_codec')
    namespace.__path__ = [str(package)]
    sys.modules[namespace.__name__] = namespace
    for name in ('controller', 'telemetry', 'protocol'):
        spec = importlib.util.spec_from_file_location(f'jetson_codec.{name}', package/f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    oracle = sys.modules['jetson_codec.protocol']
    for n in range(256):
        payload = bytes([0xAA, 0x20 | (n & 15), n, n, 255-n, n])
        assert lib.salus_crc8(payload, len(payload)) == oracle.crc8_maxim(payload)
    class Command(ctypes.Structure):
        _fields_ = [('flags', ctypes.c_uint8), ('steer', ctypes.c_int8),
                    ('speed', ctypes.c_uint16), ('brake', ctypes.c_uint8)]
    lib.salus_protocol_reset.argtypes = [ctypes.c_void_p]
    lib.salus_protocol_feed.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint64]
    lib.salus_protocol_command.argtypes = [ctypes.c_void_p, ctypes.c_uint64,
                                           ctypes.POINTER(Command)]
    lib.salus_protocol_command.restype = ctypes.c_bool
    state = ctypes.create_string_buffer(256)  # ample aligned opaque state storage
    for direction in (-1, 1):
        for bits in range(8):
            command = oracle.CommandState(drive_enabled=bool(bits & 1),
                estop=bool(bits & 2), hazard_enabled=bool(bits & 4),
                steer_pct=-73, speed_mps=direction * 1.23, brake_pct=42)
            frame = oracle.encode_pi_frame(command)
            lib.salus_protocol_reset(state)
            for byte in frame:
                lib.salus_protocol_feed(state, byte, 100)
            decoded = Command()
            assert lib.salus_protocol_command(state, 100, ctypes.byref(decoded))
            expected_flags = (bits & 1) * 2 | ((bits >> 1) & 1) | ((bits >> 2) & 1) * 8
            expected_flags |= 4 if direction < 0 else 0
            assert (decoded.flags, decoded.steer, decoded.speed, decoded.brake) == (
                expected_flags, -73, 123, 42)
    raw = bytes([0x55,4,255,255,0,128,0])
    frame = raw + bytes([lib.salus_crc8(raw,len(raw))])
    telemetry = oracle.decode_esp_frame(frame)
    assert telemetry.speed_mps is None and telemetry.steer_deg is None
    assert oracle.EspFrameParser().feed(b'noise'+frame+frame) == [frame,frame]
    print('Jetson codec: 256 CRC vectors, 16 command combinations and unavailable telemetry passed')
