# -*- coding: utf-8 -*-
"""
state_reader.py —— 读取采集进程产出的 state.json，并解析成规范化记录。

★ 本模块只做 open().read() + json.loads()，不加锁、不写、不删 —— 零干扰。
  采集侧（reader / mock_device）用「写临时文件 + os.replace」原子替换，
  所以这里读到的永远是完整 JSON，不会读到半个文件。
"""

import os
import json
import time
import math

# 200ms TTL 缓存：避免每个 HTTP 请求都去读盘
_CACHE = {"path": None, "mtime": 0.0, "ts": 0.0, "raw": None, "ttl": 0.2, "error": None}
MAX_STATE_AGE_MS = 5000
SCREEN_MAX_AGE_MS = 2000
_SCREEN_PROGRESS = {"path": None, "sequence": None, "at": 0.0}
# FRM1 ABI order, matching cabinet.protocol.FEATURES. Do not use dictionary
# insertion order or display labels to assign a measurement to an axis/band.
FEATURE_NAMES = tuple(
    ['%s_a_%s' % (kind, axis) for kind in ('rms', 'pp', 'kurt') for axis in 'xyz'] +
    ['banda%d' % i for i in range(8)] +
    ['%s_b_%s' % (kind, axis) for kind in ('rms', 'pp', 'kurt') for axis in 'xyz'] +
    ['bandb%d' % i for i in range(8)] + ['ratio_ab', 'current', 'temp', 'pressure', 'rpm'])


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_raw(path, ttl=None):
    """返回 (raw_dict_or_None, age_ms, error_str_or_None)。"""
    now = time.time()
    if ttl is None:
        ttl = _CACHE["ttl"]
    if _CACHE["path"] == path and 0 <= (now - _CACHE["ts"]) < ttl:
        age = int((now - _CACHE["mtime"]) * 1000) if _CACHE["raw"] is not None else -1
        return _CACHE["raw"], age, _CACHE.get("error")

    try:
        st = os.stat(path)
    except OSError as e:
        error = "state.json not found (%s)" % e.__class__.__name__
        _CACHE.update({"path": path, "ts": now, "raw": None, "error": error})
        return None, -1, error

    try:
        with open(path, "r", encoding="utf-8") as f:
            # Use the opened inode: the producer can atomically replace the path.
            st = os.fstat(f.fileno())
            raw = json.loads(f.read())
        if not isinstance(raw, dict):
            raise ValueError('State root must be an object')
    except (OSError, ValueError) as e:
        error = "state.json unreadable (%s)" % e.__class__.__name__
        _CACHE.update({"path": path, "ts": now, "raw": None, "error": error})
        return None, -1, error

    now = time.time()
    _CACHE.update({"path": path, "ts": now, "mtime": st.st_mtime, "raw": raw, "error": None})
    return raw, int((now - st.st_mtime) * 1000), None


def _fnum(v):
    """转 float；无法转换或明显无效返回 None（★ 绝不用 0 代替）。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _screen_number(v):
    if not isinstance(v, (str, int, float)):
        return None
    number = _fnum(v)
    return number if number is not None and abs(number) <= 1000000000 else None


def _screen_measurements(disp, rec):
    # Use the same five-second means as HDMI, never raw codes or frame features.
    if disp.get("panel_schema") != "industrial-v2":
        return
    current = _screen_number(disp.get("daily_current_value"))
    if (disp.get("daily_current_valid") == "1" and
            disp.get("daily_current_unit") == "A" and current is not None):
        rec["current_a"] = current
        rec["current_kind"] = disp.get("daily_current_kind")
    pressure = _screen_number(disp.get("daily_pressure_value"))
    unit = disp.get("daily_pressure_unit")
    if (disp.get("daily_pressure_valid") == "1" and
            unit in ("Pa", "kPa") and pressure is not None):
        rec["pressure_pa"] = pressure * (1000.0 if unit == "kPa" else 1.0)
        rec["pressure_kind"] = disp.get("daily_pressure_kind")


def _inum(v):
    """整数语义的字段用这个：整数值返回 int（避免 JSON 里出现 3.0 这种）。"""
    f = _fnum(v)
    if f is None:
        return None
    return int(round(f))


def _uint32(v):
    number = _fnum(v)
    if number is None or not number.is_integer() or not 0 <= number <= 0xffffffff:
        return None
    return int(number)


def _deadline_current(display, key):
    # Match the native HMI's monotonic deadline gate on every read, including
    # cached/retained frames. File TTL and static fresh flags do not extend it.
    text = display.get(key)
    if not isinstance(text, str) or not text or len(text) > 20 or any(c < '0' or c > '9' for c in text):
        return False
    deadline = int(text)
    now = int(time.monotonic() * 1000)
    return 0 <= deadline <= 0xffffffffffffffff and 0 <= deadline - now <= 2500


def _feature_deadline_current(display):
    return _deadline_current(display, 'panel_raw_features_deadline_ms')


def _frame_age(display, frame, status):
    # The observer's age includes both PL time and time since receipt. Its
    # retained-frame display remains authoritative on EMPTY mailbox polls.
    age = display.get('frame_age')
    if age is not None:
        if isinstance(age, str) and age.endswith(' ms'):
            age = age[:-3]
        return _uint32(age)
    end = _uint32(frame.get('end_ms')) if frame else None
    now = _uint32(status.get('uptime_ms'))
    if end is None or now is None:
        return None
    age = (now - end) & 0xffffffff
    # Match the observer's allowance for a frame completing just after the
    # status snapshot, including uint32 uptime rollover.
    return 0 if age >= 0xffffffff - 99 else age


def _b(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().upper()
        return s in ("1", "YES", "TRUE", "ON", "OK", "VALID")
    return False


def parse_validity(text):
    """'RPM:1 ADC:1 TEMP:0 PRESS:0' -> {'rpm':True,'adc':True,'temperature':False,'pressure':False}"""
    out = {"rpm": False, "adc": False, "temperature": False, "pressure": False}
    if not text:
        return out
    for part in str(text).replace(",", " ").split():
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        k = k.strip().upper()
        ok = _b(v)
        if k == "RPM":
            out["rpm"] = ok
        elif k == "ADC":
            out["adc"] = ok
        elif k == "TEMP":
            out["temperature"] = ok
        elif k == "PRESS":
            out["pressure"] = ok
    return out


def split_faults(text):
    """'DIAG_LOSS, AUX_LOSS' -> ['DIAG_LOSS','AUX_LOSS']；'NONE'/''/None -> []"""
    if not text:
        return []
    s = str(text).strip()
    if not s or s.upper() in ("NONE", "--", "NULL"):
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def derive(raw):
    """
    把 state.json 解析成规范化记录。
    ★ 无效测量值一律 None —— 前端据此显示 `--`，绝不显示 0。
    """
    rec = {
        "link_ok": 0,
        "message": None,
        "mode": None,
        "alarm": None,
        "action": None,
        "inhibit": None,
        "configured": None,
        "uptime_ms": None,
        "sequence": None,
        "rpm": None,
        "temp_c": None,
        "current_raw": None,
        "current_a": None,
        "pressure_pa": None,
        "current_kind": None,
        "pressure_kind": None,
        "pressure_ok": None,
        "environment_state": "UNAVAILABLE",
        "environment_hardware_profile": "AHT20_ONLY_V1",
        "aht_valid": False,
        "inlet_temperature_c": None,
        "relative_humidity_pct": None,
        "validity": None,
        "faults": [],
        "latched": [],
        "queue": None,
        "drops": None,
        "frame_id": None,
        "frame_age_ms": None,
        "frame_state": None,
        "quality": None,
        "quality_reasons": None,
        "feature_count": 0,
        "features": None,
        "has_valid_frame": False,
        "display": {},
    }
    if not isinstance(raw, dict) or not raw:
        return rec

    disp = raw.get("display") or {}
    obs = raw.get("observation") or {}
    if not isinstance(disp, dict) or not isinstance(obs, dict):
        rec["message"] = "INVALID_STATE_OBJECTS"
        return rec
    status = obs.get("status") or {}
    frame = obs.get("frame") or None

    frame_test = isinstance(frame, dict) and (
        frame.get('state') == 'REJECTED_TEST' or frame.get('test') is True or
        (type(frame.get('quality')) is int and bool(frame['quality'] & 0x4000)))
    if (not isinstance(status, dict) or (frame is not None and not isinstance(frame, dict)) or
            disp.get("link") != "FCB1 + EDG1 ABI OK" or
            disp.get("frame_state") == "REJECTED_TEST" or frame_test or raw.get("_mock")):
        rec["message"] = "SOURCE_OFFLINE_OR_TEST"
        rec["validity"] = "RPM:0 ADC:0 TEMP:0 PRESS:0"
        return rec
    # Legacy ENV1 may contain diagnostics for an uninstalled BMP280. They are
    # not product measurements, even when reading an older producer snapshot.
    rec["display"] = {key: value for key, value in disp.items()
                      if not (key.startswith('environment_bmp_') or key.startswith('ambient_pressure'))}
    rec["link_ok"] = 1
    rec["message"] = disp.get("message")
    rec["mode"] = disp.get("mode")
    rec["action"] = disp.get("action")
    rec["alarm"] = _inum(disp.get("alarm"))
    rec["inhibit"] = 1 if _b(disp.get("inhibit")) else 0
    rec["configured"] = 1 if _b(disp.get("configured")) else 0
    rec["uptime_ms"] = _inum(status.get("uptime_ms"))
    if rec["uptime_ms"] is None:
        rec["uptime_ms"] = _inum(disp.get("uptime_ms"))
    rec["sequence"] = _inum(disp.get("sequence"))

    rec["validity"] = disp.get("validity")
    val = parse_validity(rec["validity"])

    if val["rpm"]:
        rec["rpm"] = _inum(status.get("measured_rpm"))
    if val["temperature"]:
        raw_t = _fnum(status.get("temp_raw_1_16_C"))
        rec["temp_c"] = (raw_t / 16.0) if raw_t is not None else None
    if val["adc"]:
        rec["current_raw"] = _inum(status.get("current_distance_raw_code"))
    # 实际 PWM 占空比：PL 的 applied_pwm_counts 是 0..4000（4000 = 100%）。
    # 与 HDMI 界面上的 PWM 曲线同源，便于两边对照。
    _pwm_counts = _inum(status.get("applied_pwm_counts"))
    rec["pwm"] = round(_pwm_counts / 40.0, 2) if _pwm_counts is not None else None
    rec["pressure_ok"] = 1 if val["pressure"] else 0
    _screen_measurements(disp, rec)
    inlet = _fnum(disp.get('inlet_temperature_c'))
    humidity = _fnum(disp.get('relative_humidity_pct'))
    if (disp.get('environment_hardware_profile') == 'AHT20_ONLY_V1' and
            disp.get('environment_installed_sensors') == 'AHT20' and
            disp.get('environment_state') == 'VALID' and disp.get('inlet_source') == 'AHT20' and
            _deadline_current(disp, 'environment_aht_deadline_ms') and
            inlet is not None and -40 <= inlet <= 85 and humidity is not None and 0 <= humidity <= 100):
        rec.update(environment_state='VALID', aht_valid=True,
                   inlet_temperature_c=inlet, relative_humidity_pct=humidity)

    rec["faults"] = split_faults(disp.get("faults"))
    rec["latched"] = split_faults(disp.get("latched"))
    rec["queue"] = _inum(disp.get("queue"))
    rec["drops"] = _inum(disp.get("drops"))
    rec["frame_state"] = disp.get("frame_state")
    rec["quality"] = disp.get("quality")
    rec["quality_reasons"] = disp.get("quality_reasons")

    display_id = _uint32(disp.get('frame_id'))
    rec['frame_id'] = _uint32(frame.get('frame_id')) if frame else None
    if rec['frame_id'] is None:
        rec['frame_id'] = display_id
    rec['frame_age_ms'] = _frame_age(disp, frame, status)
    if frame:
        if frame.get("state"):
            rec["frame_state"] = frame.get("state")

    # Numeric presence is not evidence of a qualified physical feature frame.
    # Keep raw diagnostics on the dedicated RAW display, never label them valid here.
    qualified = (disp.get("frame_fresh") == "1" and
                 disp.get("panel_vibration_valid") == "1" and
                 _feature_deadline_current(disp) and
                 disp.get("frame_calibrated") == "1" and
                 disp.get("frame_contract_current") == "1" and
                 disp.get("quality") == "0x00000000" and
                 rec['frame_id'] is not None and
                 rec['frame_age_ms'] is not None and 0 <= rec['frame_age_ms'] <= 1000 and
                 rec["frame_state"] != "REJECTED_TEST")
    if not qualified:
        return rec

    if frame and frame.get('state') == 'RECEIVED_REAL':
        # A present frame must be complete on its own. Never repair missing or
        # invalid values with a rounded display value or an older frame.
        calibration = frame.get('calibration_id')
        if (frame.get('test') is not False or type(calibration) is not int or calibration <= 0 or
                type(frame.get('quality')) is not int or frame['quality'] != 0 or
                _uint32(frame.get('frame_id')) != rec['frame_id'] or
                (display_id is not None and display_id != rec['frame_id'])):
            return rec
        values = frame.get('values')
        if not isinstance(values, dict) or set(values) != set(FEATURE_NAMES):
            return rec
        feats = [_fnum(values.get(name)) for name in FEATURE_NAMES]
    elif frame and frame.get('state') == 'EMPTY' and 'values' not in frame and 'frame_id' not in frame:
        # EMPTY means no new queued frame, not loss of the observer's still
        # fresh, calibrated retained frame. The same qualification gate applies.
        feats = [_fnum(disp.get('feature_' + name)) for name in FEATURE_NAMES]
    else:
        return rec
    if all(value is not None for value in feats):
        rec['features'] = feats
        rec['feature_count'] = len(FEATURE_NAMES)
        rec['has_valid_frame'] = True

    return rec


def read_state(path):
    """返回 (rec, age_ms, error)。"""
    raw, age, err = read_raw(path)
    if not err and not 0 <= age < MAX_STATE_AGE_MS:
        err = "STATE_STALE_OR_CLOCK_INVALID"
    rec = derive(None if err else raw)
    if not rec["link_ok"] and not err:
        err = rec.get("message") or "SOURCE_OFFLINE"
    if err:
        rec["message"] = err
        rec["validity"] = "RPM:0 ADC:0 TEMP:0 PRESS:0"
    # A rewritten file with a frozen sequence must not extend measurement life.
    disp = rec.get("display") or {}
    now = time.monotonic()
    source_ok = (not err and 0 <= age <= SCREEN_MAX_AGE_MS and
                 disp.get("panel_schema") == "industrial-v2" and
                 _screen_number(disp.get("sequence")) is not None)
    sequence = str(disp.get("sequence"))
    if source_ok and (_SCREEN_PROGRESS["path"] != path or
                      _SCREEN_PROGRESS["sequence"] != sequence):
        _SCREEN_PROGRESS.update(path=path, sequence=sequence, at=now)
    if not source_ok or now - _SCREEN_PROGRESS["at"] > SCREEN_MAX_AGE_MS / 1000.0:
        for field in ("current_a", "pressure_pa", "current_kind", "pressure_kind"):
            rec[field] = None
    return rec, age, err


def feature_names():
    return list(FEATURE_NAMES)
