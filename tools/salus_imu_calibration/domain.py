"""Pure calibration, capture validation and profile application (stdlib only)."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import statistics
import uuid

G = 9.80665
POSES = ('x+', 'x-', 'y+', 'y-', 'z+', 'z-')
LIMITS = dict(min_samples=100, min_span_s=9.0, max_gap_s=0.1,
              accel_std_m_s2=0.1, gyro_std_rad_s=0.005,
              gyro_bias_norm_rad_s=0.05, temperature_span_c=2.0,
              temperature_difference_warning_c=10.0)


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def vector(value, name):
    if not isinstance(value, list) or len(value) != 3 or not all(map(finite, value)):
        raise ValueError(f'{name}: expected three finite numbers')
    return value


def identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError('device_id must be a nonempty board label, at most 128 characters')
    return value


def sensor_check(sample):
    if sample.get('calibrated') is not False or 'calibration' in sample:
        raise ValueError('Expected uncorrected snapshot; do not apply calibration twice')
    if (sample.get('profile') != 1 or sample.get('chip_ids') != [0x1E, 0x0F] or
            sample.get('frame') != 'bosch_sensor' or sample.get('state') != 'running'):
        raise ValueError('Expected running BMI088 acquisition profile 1 in Bosch frame')


def summarize(capture):
    if capture.get('schema_version') != 1 or capture.get('kind') != 'salus_bmi088_capture':
        raise ValueError('Unsupported capture schema')
    identity(capture.get('device_id'))
    samples = capture.get('samples')
    if not isinstance(samples, list) or not 100 <= len(samples) <= 20000:
        raise ValueError('Capture must contain 100..20000 paired snapshots')
    series = {key: [] for key in ('accel', 'gyro', 'temperature')}
    last_time, last_seq = {}, {}
    first_time, init_attempt = {}, None
    for sample in samples:
        sensor_check(sample)
        attempt = sample.get('init_attempts')
        if not isinstance(attempt, int) or attempt < 1:
            raise ValueError('Missing initialization generation')
        if init_attempt is not None and attempt != init_attempt:
            raise ValueError('IMU reinitialized during capture')
        init_attempt = attempt
        for key, unit in (('accel', 'm_s2'), ('gyro', 'rad_s')):
            v = sample[key]
            if v.get('valid') is not True or v.get('saturated') is not False:
                raise ValueError(f'{key}: invalid or saturated sample')
            stamp, seq, age = v.get('timestamp_us'), v.get('sequence'), v.get('age_us')
            if (not isinstance(stamp, int) or stamp <= 0 or not isinstance(seq, int) or seq < 1 or
                    not finite(age) or not 0 <= age <= 50000):
                raise ValueError(f'{key}: invalid timestamp, sequence or age')
            if key in last_time:
                if stamp <= last_time[key] or seq <= last_seq[key]:
                    raise ValueError(f'{key}: duplicate, reversed timestamp or reset')
                if stamp-last_time[key] > LIMITS['max_gap_s']*1e6:
                    raise ValueError(f'{key}: sample gap exceeds 100 ms')
            else:
                first_time[key] = stamp
            last_time[key], last_seq[key] = stamp, seq
            series[key].append(vector(v.get(unit), key))
        temp = sample['temperature']
        if temp.get('valid') is not True or not finite(temp.get('celsius')) or not -40 <= temp['celsius'] <= 85:
            raise ValueError('Missing/invalid sensor temperature')
        series['temperature'].append(temp['celsius'])
    spans = {k: (last_time[k]-first_time[k])/1e6 for k in ('accel', 'gyro')}
    if min(spans.values()) < LIMITS['min_span_s']:
        raise ValueError('Need at least 9 seconds of unique data from each sensor')
    temperatures = series['temperature']
    if max(temperatures)-min(temperatures) > LIMITS['temperature_span_c']:
        raise ValueError('Temperature changed more than 2 C: allow warmup and repeat')
    result = {'samples': len(samples), 'duration_s': spans,
              'temperature_c': statistics.mean(temperatures),
              'temperature_range_c': [min(temperatures), max(temperatures)]}
    for key in ('accel', 'gyro'):
        axes = list(zip(*series[key]))
        means = [statistics.mean(a) for a in axes]
        variances = [statistics.variance(a) for a in axes]
        limit = LIMITS['accel_std_m_s2' if key == 'accel' else 'gyro_std_rad_s']
        if any(math.sqrt(v) > limit for v in variances):
            raise ValueError(f'{key}: movement/vibration detected; repeat while stationary')
        result[key] = {'mean': means, 'variance': variances}
    if abs(math.sqrt(sum(x*x for x in result['accel']['mean']))-G) > 1.5:
        raise ValueError('Stationary acceleration magnitude is not near gravity')
    if math.sqrt(sum(x*x for x in result['gyro']['mean'])) > LIMITS['gyro_bias_norm_rad_s']:
        raise ValueError('Excessive gyro mean: possible rotation or sensor fault')
    return result


def new_profile(device_id, base=None):
    if base is not None:
        validate_profile(base, device_id)
        result = deepcopy(base)
        result['previous_profile_id'] = base['profile_id']
    else:
        result = dict(schema_version=1, kind='salus_bmi088_calibration',
                      device_id=identity(device_id), frame='bosch_sensor',
                      chip_ids=[0x1E, 0x0F], acquisition_profile=1,
                      gyro=None, accel=None)
    result.update(profile_id=str(uuid.uuid4()), created_utc=datetime.now(timezone.utc).isoformat(),
                  quality_limits=deepcopy(LIMITS))
    return result


def calibrate_gyro(capture, base=None):
    stats = summarize(capture)
    result = new_profile(capture['device_id'], base)
    result['gyro'] = dict(method='stationary_mean', bias_rad_s=stats['gyro']['mean'],
        variance_rad2_s2=stats['gyro']['variance'], temperature_c=stats['temperature_c'],
        temperature_range_c=stats['temperature_range_c'], samples=stats['samples'],
        duration_s=stats['duration_s']['gyro'])
    validate_profile(result, capture['device_id'])
    return result


def calibrate_accel(captures, base=None):
    if len(captures) != 6:
        raise ValueError('Exactly six captures required: x+, x-, y+, y-, z+, z-')
    device_id = identity(captures[0]['device_id'])
    by_pose = {}
    for capture in captures:
        if capture['device_id'] != device_id:
            raise ValueError('Cannot combine captures from different boards')
        pose = capture.get('pose')
        if pose not in POSES or pose in by_pose:
            raise ValueError('Missing, duplicate or unsupported pose')
        stats = summarize(capture)
        axis = 'xyz'.index(pose[0])
        mean = stats['accel']['mean']
        expected = G if pose[1] == '+' else -G
        if abs(mean[axis]-expected) > 1.5 or any(abs(mean[i]) > 1.5 for i in range(3) if i != axis):
            raise ValueError(f'{pose}: wrong face/sign or excessive tilt')
        by_pose[pose] = stats
    if set(by_pose) != set(POSES):
        raise ValueError('Incomplete pose set')
    temps = [s['temperature_c'] for s in by_pose.values()]
    if max(temps)-min(temps) > 5:
        raise ValueError('Six poses differ by more than 5 C; repeat after warmup')
    offsets, scales = [], []
    for i, axis in enumerate('xyz'):
        positive = by_pose[axis+'+']['accel']['mean'][i]
        negative = by_pose[axis+'-']['accel']['mean'][i]
        offsets.append((positive+negative)/2)
        scales.append(2*G/(positive-negative))
    for pose, stats in by_pose.items():
        target = [0.0]*3
        target['xyz'.index(pose[0])] = G if pose[1] == '+' else -G
        corrected = [(stats['accel']['mean'][i]-offsets[i])*scales[i] for i in range(3)]
        if math.sqrt(sum((a-b)**2 for a, b in zip(corrected, target))) > 0.35:
            raise ValueError(f'{pose}: fit residual exceeds 0.35 m/s2; check placement')
    result = new_profile(device_id, base)
    variances = [statistics.mean(s['accel']['variance'][i]*scales[i]**2
                  for s in by_pose.values()) for i in range(3)]
    result['accel'] = dict(method='six_position_diagonal', offset_m_s2=offsets, scale=scales,
        variance_m2_s4=variances, temperature_c=statistics.mean(temps), poses=by_pose)
    validate_profile(result, device_id)
    return result


def validate_profile(profile, device_id):
    identity(device_id)
    if (profile.get('schema_version') != 1 or profile.get('kind') != 'salus_bmi088_calibration' or
        profile.get('device_id') != device_id or profile.get('frame') != 'bosch_sensor' or
        profile.get('chip_ids') != [0x1E, 0x0F] or profile.get('acquisition_profile') != 1):
        raise ValueError('Profile schema, board identity or acquisition configuration mismatch')
    if not isinstance(profile.get('profile_id'), str) or not profile['profile_id']:
        raise ValueError('Missing profile identity')
    if profile.get('gyro') is None and profile.get('accel') is None:
        raise ValueError('Profile contains no calibration')
    for key in ('gyro', 'accel'):
        data = profile.get(key)
        if data is None:
            continue
        if not isinstance(data, dict) or not finite(data.get('temperature_c')) or not -40 <= data['temperature_c'] <= 85:
            raise ValueError('Invalid calibration temperature')
        if key == 'gyro':
            bias = vector(data.get('bias_rad_s'), 'gyro bias')
            if data.get('method') != 'stationary_mean' or math.sqrt(sum(x*x for x in bias)) > 0.05:
                raise ValueError('Unsupported gyro calibration or excessive bias')
            variance = vector(data.get('variance_rad2_s2'), 'gyro variance')
        else:
            bias = vector(data.get('offset_m_s2'), 'accel offset')
            scales = vector(data.get('scale'), 'accel scale')
            if data.get('method') != 'six_position_diagonal' or any(abs(x)>1.5 for x in bias) or any(not 0.8<=x<=1.2 for x in scales):
                raise ValueError('Unsupported accel calibration, offset or scale')
            variance = vector(data.get('variance_m2_s4'), 'accel variance')
        if any(v < 0 for v in variance):
            raise ValueError('Variance cannot be negative')
    return profile


def apply_profile(snapshot, profile, device_id):
    validate_profile(profile, device_id)
    sensor_check(snapshot)
    result = deepcopy(snapshot)
    result['calibration'] = dict(profile_id=profile['profile_id'], device_id=device_id,
                                 gyro_applied=False, accel_applied=False, warnings=[])
    for key, unit in (('gyro', 'rad_s'), ('accel', 'm_s2')):
        values = vector(list(snapshot[key][unit]), key)
        result[key]['uncorrected_'+unit] = values
        calibration = profile.get(key)
        if calibration is None or not snapshot[key]['valid'] or snapshot[key]['saturated']:
            continue
        age = snapshot[key].get('age_us')
        if not finite(age) or not 0 <= age <= 50000:
            raise ValueError('Cannot correct a stale vector')
        if key == 'gyro':
            result[key][unit] = [a-b for a, b in zip(values, calibration['bias_rad_s'])]
        else:
            result[key][unit] = [(a-b)*s for a, b, s in zip(values, calibration['offset_m_s2'], calibration['scale'])]
        result['calibration'][key+'_applied'] = True
        temperature = snapshot.get('temperature', {})
        if not temperature.get('valid') or not finite(temperature.get('celsius')):
            result['calibration']['warnings'].append(key+': temperature unavailable')
        elif abs(temperature['celsius']-calibration['temperature_c']) > 10:
            result['calibration']['warnings'].append(key+': temperature differs by more than 10 C; verify bias')
    result['calibrated'] = result['calibration']['gyro_applied'] and result['calibration']['accel_applied']
    return result
