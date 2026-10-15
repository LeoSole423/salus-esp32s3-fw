"""Deterministic known-error captures; no board or serial dependency."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from salus_imu_calibration.domain import (
    G, POSES, summarize, calibrate_gyro, calibrate_accel, apply_profile, validate_profile,
)
from salus_imu_calibration.storage import load_json, save_new
from imu_calibration import capture
from usb_diagnostics import crc8, read_diagnostic, decode_imu

BIAS = [0.01, -0.005, 0.002]
OFFSET = [0.12, -0.08, 0.05]
SCALE = [1.02, 0.98, 1.01]


def fixture(pose='z+', device='SALUS-003'):
    target = [0., 0., 0.]
    target['xyz'.index(pose[0])] = G if pose[1] == '+' else -G
    samples = []
    for i in range(501):
        stamp = 1000000+i*20000
        noise = ((i % 3)-1)*0.00001
        samples.append(dict(state='running', profile=1, chip_ids=[30,15], frame='bosch_sensor',
            init_attempts=1, calibrated=False,
            accel=dict(valid=True, saturated=False, sequence=8*i+1, timestamp_us=stamp,
                       age_us=2000, raw=[1,2,3], m_s2=[target[k]/SCALE[k]+OFFSET[k]+noise for k in range(3)]),
            gyro=dict(valid=True, saturated=False, sequence=8*i+1, timestamp_us=stamp+1000,
                      age_us=1000, raw=[4,5,6], rad_s=[b+noise for b in BIAS]),
            temperature=dict(valid=True, celsius=25., timestamp_us=stamp)))
    return dict(schema_version=1, kind='salus_bmi088_capture', device_id=device,
                pose=pose, samples=samples)


class CalibrationTests(unittest.TestCase):
    def test_known_bias_and_six_position_recovery(self):
        gyro = calibrate_gyro(fixture())
        profile = calibrate_accel([fixture(p) for p in POSES], gyro)
        for got, expected in zip(profile['gyro']['bias_rad_s'], BIAS):
            self.assertAlmostEqual(got, expected, places=6)
        for got, expected in zip(profile['accel']['offset_m_s2'], OFFSET):
            self.assertAlmostEqual(got, expected, places=6)
        for got, expected in zip(profile['accel']['scale'], SCALE):
            self.assertAlmostEqual(got, expected, places=6)
        raw = fixture('x-')['samples'][1]
        corrected = apply_profile(raw, profile, 'SALUS-003')
        self.assertAlmostEqual(corrected['accel']['m_s2'][0], -G, places=5)
        self.assertAlmostEqual(corrected['gyro']['rad_s'][0], 0, places=5)
        self.assertTrue(corrected['calibrated'])
        self.assertEqual(corrected['accel']['raw'], raw['accel']['raw'])
        self.assertEqual(corrected['gyro']['uncorrected_rad_s'], raw['gyro']['rad_s'])
        self.assertFalse(raw['calibrated'])

    def test_gyro_update_preserves_accel_and_previous_profile(self):
        profile = calibrate_accel([fixture(p) for p in POSES])
        self.assertIsNone(profile['gyro'])
        updated = calibrate_gyro(fixture(), profile)
        self.assertEqual(updated['accel'], profile['accel'])
        self.assertEqual(updated['previous_profile_id'], profile['profile_id'])
        self.assertIsNone(profile['gyro'])
        applied = apply_profile(fixture()['samples'][0], updated, 'SALUS-003')
        self.assertTrue(applied['calibrated'])

    def test_partial_profile_never_claims_full_calibration(self):
        profile = calibrate_gyro(fixture())
        result = apply_profile(fixture()['samples'][0], profile, 'SALUS-003')
        self.assertTrue(result['calibration']['gyro_applied'])
        self.assertFalse(result['calibration']['accel_applied'])
        self.assertFalse(result['calibrated'])

    def test_double_correction_and_calibrated_input_rejected(self):
        p=calibrate_gyro(fixture()); result=apply_profile(fixture()['samples'][0],p,'SALUS-003')
        with self.assertRaises(ValueError): apply_profile(result,p,'SALUS-003')
        c=fixture(); c['samples'][0]=result
        with self.assertRaises(ValueError): calibrate_gyro(c)

    def test_bad_capture_quality(self):
        mutations = {
            'motion': lambda s: s['gyro']['rad_s'].__setitem__(0, 0.5),
            'invalid': lambda s: s['gyro'].__setitem__('valid', False),
            'saturation': lambda s: s['accel'].__setitem__('saturated', True),
            'age': lambda s: s['gyro'].__setitem__('age_us', 50001),
            'nan': lambda s: s['accel']['m_s2'].__setitem__(0, float('nan')),
            'reset': lambda s: s.__setitem__('init_attempts', 2),
            'duplicate': lambda s: s['gyro'].__setitem__('sequence', 1),
            'time': lambda s: s['accel'].__setitem__('timestamp_us', 1),
            'temp': lambda s: s['temperature'].__setitem__('celsius', 29),
            'id': lambda s: s.__setitem__('chip_ids', [0,15]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                c = fixture(); mutate(c['samples'][250])
                with self.assertRaises(ValueError): summarize(c)
        c = fixture(); c['samples'] = c['samples'][::10]
        with self.assertRaises(ValueError): summarize(c)
        c = fixture(); c['samples'] = c['samples'][:110]
        with self.assertRaises(ValueError): summarize(c)
        c = fixture()
        for s in c['samples']: s['gyro']['rad_s'] = [0.1,0,0]
        with self.assertRaises(ValueError): summarize(c)

    def test_six_pose_errors(self):
        captures = [fixture(p) for p in POSES]
        for change in ('duplicate','board','face','tilt','thermal'):
            c = deepcopy(captures)
            if change == 'duplicate': c[1]['pose'] = 'x+'
            elif change == 'board': c[1]['device_id'] = 'other'
            elif change == 'face': c[0]['pose'],c[1]['pose'] = c[1]['pose'],c[0]['pose']
            elif change == 'tilt':
                for s in c[0]['samples']: s['accel']['m_s2'][1] = 0.8
            else:
                for s in c[1]['samples']: s['temperature']['celsius'] = 31
            with self.subTest(change=change), self.assertRaises(ValueError): calibrate_accel(c)
        with self.assertRaises(ValueError): calibrate_accel(captures[:5])

    def test_invalid_profile_and_identity(self):
        p = calibrate_gyro(fixture())
        with self.assertRaises(ValueError): validate_profile(p, 'another-board')
        for field,value in [('schema_version',2),('acquisition_profile',2),('frame','base_link')]:
            c = deepcopy(p); c[field]=value
            with self.assertRaises(ValueError): validate_profile(c, 'SALUS-003')
        p['gyro']['bias_rad_s'][0] = float('inf')
        with self.assertRaises(ValueError): validate_profile(p, 'SALUS-003')

    def test_invalid_vectors_not_corrected_and_temperature_warning(self):
        p = calibrate_gyro(fixture()); sample = fixture()['samples'][0]
        sample['gyro']['valid'] = False
        result = apply_profile(sample,p,'SALUS-003')
        self.assertFalse(result['calibration']['gyro_applied'])
        sample['gyro']['valid'] = True; sample['temperature']['celsius'] = 40
        self.assertTrue(apply_profile(sample,p,'SALUS-003')['calibration']['warnings'])
        sample['gyro']['age_us'] = 50001
        with self.assertRaises(ValueError): apply_profile(sample,p,'SALUS-003')

    def test_atomic_storage_refuses_replace_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'profile.json'; p = calibrate_gyro(fixture())
            save_new(path,p); self.assertEqual(load_json(path),p)
            with self.assertRaises(FileExistsError): save_new(path, {'different':True})
            self.assertEqual(load_json(path),p)
            invalid = Path(directory)/'bad.json'
            for content in ('{"a":1,"a":2}', '{"a":NaN}', '[]'):
                invalid.write_text(content)
                with self.assertRaises(ValueError): load_json(invalid)

    def test_capture_with_virtual_clock_and_real_quality_checks(self):
        data = iter(fixture()['samples']); now=[0.0]
        result = capture(None,'SALUS-003','z+',10,lambda port:deepcopy(next(data)),
                         clock=lambda:now[0],sleep=lambda t:now.__setitem__(0,now[0]+t))
        self.assertGreaterEqual(len(result['samples']),490)
        with self.assertRaises(ValueError):
            capture(None,'SALUS-003','z+',10,lambda port:{'state':'fault'},
                    clock=lambda:0,sleep=lambda t:None)

    def test_fragmented_usb_and_request_is_diagnostic_only(self):
        frame = bytearray(112); frame[:8] = bytes([0x5A,0x10,2,112,1,7,30,15])
        struct.pack_into('<I',frame,12,1)
        frame[108] = 1; frame[-1]=crc8(frame[:-1])
        corrupt = bytearray(frame); corrupt[-1] ^= 1
        class Port:
            in_waiting=3
            def __init__(self): self.writes=[]; self.data=b''
            def reset_input_buffer(self): self.data=b''
            def write(self, request):
                self.writes.append(request); self.data=b'noise'+bytes(corrupt)+bytes(frame); return len(request)
            def read(self,n):
                piece=self.data[:min(n,3)]; self.data=self.data[len(piece):]; return piece
        port=Port(); result=read_diagnostic(port,2)
        self.assertEqual(result,bytes(frame))
        self.assertEqual(port.writes[0][:6],bytes([0xAB,0x10,2,0,0,0]))
        self.assertEqual(decode_imu(result)['profile'],1)

    def test_offline_cli_preserves_base_and_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory); c=temp/'capture.json'; c.write_text(json.dumps(fixture()))
            base=temp/'base.json'; save_new(base, calibrate_accel([fixture(p) for p in POSES]))
            output=temp/'updated.json'
            cmd=[sys.executable,str(ROOT/'tools/imu_calibration.py'),'gyro','--capture',str(c),
                 '--base',str(base),'--output',str(output)]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(load_json(output)['accel'],load_json(base)['accel'])
            self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,2)


if __name__ == '__main__': unittest.main()
