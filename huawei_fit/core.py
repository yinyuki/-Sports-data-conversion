"""Local Huawei exercise archive -> standard FIT Activity conversion."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Callable
import hashlib
import json
import math
import os
import tempfile
import uuid
import zipfile

VERSION = "1.1.1"
# Packaging/UI updates do not change FIT contents or invalidate prior exports.
FIT_FORMAT_VERSION = "1.0.1"
ZIP_MAX_BYTES = 50_000_000
FIT_EPOCH = 631065600
# This position recurs at the ends and gaps of Huawei tracks.
HUAWEI_GPS_PLACEHOLDER = (90.0, -80.0)
SPORTS = {
    257: ("户外步行", "walking", "generic", "walk"),
    258: ("户外跑步", "running", "generic", "run"),
    259: ("户外骑行", "cycling", "generic", "ride"),
    260: ("登山", "hiking", "generic", "hike"),
    281: ("室内步行", "walking", "indoor_walking", "indoor_walk"),
    282: ("徒步", "hiking", "generic", "hike"),
    264: ("室内跑步", "running", "treadmill", "indoor_run"),
    265: ("室内骑行", "cycling", "indoor_cycling", "indoor_ride"),
    129: ("羽毛球", "racket", "badminton", "badminton"),
}
COORD_MODES = {
    "auto": "自动：高德来源按 GCJ-02 转换",
    "gcj02": "指定 GCJ-02 → WGS-84",
    "wgs84": "指定 WGS-84，保留原坐标",
    "omit": "不导出 GPS 轨迹",
}


def number(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError, OverflowError):
        return default


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def object_json(value):
    obj = json.loads(value) if isinstance(value, str) else value
    if not isinstance(obj, dict):
        raise ValueError("运动汇总不是 JSON 对象")
    return obj


def offset_seconds(value: str) -> int:
    import re
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", str(value))
    if not match or int(match[2]) > 23 or int(match[3]) > 59:
        raise ValueError(f"无法识别时区：{value}")
    return (1 if match[1] == "+" else -1) * (int(match[2]) * 3600 + int(match[3]) * 60)


def detail_lines(text):
    for line in str(text or "").splitlines():
        fields = dict(part.split("=", 1) for part in line.strip().split(";") if "=" in part)
        if "tp" in fields:
            yield fields


def _gps_position(item):
    lat, lon = number(item.get("lat")), number(item.get("lon"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if (lat, lon) in ((0, 0), HUAWEI_GPS_PLACEHOLDER):
        return None
    return lat, lon


@dataclass
class Exercise:
    source: Path
    index: int
    record_id: str
    start_ms: int
    end_ms: int
    tz_offset: int
    summary: dict
    gps_points: int
    heart_points: int
    sport_code: int
    notes: list[str] = field(default_factory=list)

    @property
    def key(self):
        return self.record_id or f"{self.source}:{self.index}"

    @property
    def sport(self):
        return SPORTS.get(self.sport_code, (f"其他运动 ({self.sport_code})", "generic", "generic", "other"))

    @property
    def local_start(self):
        return datetime.fromtimestamp(self.start_ms / 1000, timezone(timedelta(seconds=self.tz_offset)))

    @property
    def duration(self):
        return number(self.summary.get("totalTime"), 0) / 1000

    @property
    def distance(self):
        return number(self.summary.get("totalDistance"), 0)


@dataclass
class ScanResult:
    exercises: list[Exercise]
    files: int
    duplicates: int
    warnings: list[str]


def scan_archive(source: Path, cancel: Event | None = None,
                 progress: Callable | None = None) -> ScanResult:
    source = Path(source).resolve()
    if not source.exists():
        raise ValueError("源路径不存在")
    files = [source] if source.is_file() else sorted(source.rglob("motion path detail data*.json"))
    if not files:
        raise ValueError("没有找到运动明细 JSON；请选择 HUAWEI_HEALTH 或运动明细文件夹")
    seen = {}
    warnings = []
    duplicates = 0
    for file_no, path in enumerate(files, 1):
        if cancel and cancel.is_set():
            raise InterruptedError("已取消扫描")
        try:
            data = read_json(path)
            if not isinstance(data, list):
                raise ValueError("文件顶层不是数组")
        except (OSError, ValueError) as exc:
            warnings.append(f"{path.name}：{exc}")
            continue
        for index, raw in enumerate(data):
            if cancel and cancel.is_set():
                raise InterruptedError("已取消扫描")
            try:
                summary = object_json(raw.get("summaryData", {}))
                start, end = int(raw["startTime"]), int(raw["endTime"])
                if start // 1000 <= FIT_EPOCH or end < start:
                    raise ValueError("开始或结束时间无效")
                if raw.get("timeZone") is None:
                    raise ValueError("缺少时区")
                tz = offset_seconds(raw["timeZone"])
                ng, nh = 0, 0
                for item in detail_lines(raw.get("detailData")):
                    if item["tp"] == "lbs":
                        if _gps_position(item) is not None:
                            ng += 1
                    elif item["tp"] in ("h-r", "i-h-r") and 0 < number(item.get("v"), 0) < 255:
                        nh += 1
                code = int(summary.get("sportType", 9999))
                ex = Exercise(path, index, str(raw.get("recordId") or ""), start, end, tz,
                              summary, ng, nh, code)
                if code not in SPORTS:
                    ex.notes.append(f"运动类型 {code} 暂按通用运动导出")
                if not ng:
                    ex.notes.append("源数据无有效 GPS，保留运动汇总和传感器数据")
                if number(summary.get("abnormalTrack"), 0):
                    ex.notes.append("华为标记为异常运动，请核对数据")
                previous = seen.get(ex.key)
                if previous:
                    duplicates += 1
                    if number(raw.get("version"), 0) <= previous[0]:
                        continue
                seen[ex.key] = (number(raw.get("version"), 0), ex)
            except (KeyError, ValueError, TypeError, OverflowError) as exc:
                warnings.append(f"{path.name} 第 {index + 1} 条：{exc}")
        if progress:
            progress(file_no, len(files), f"已扫描 {file_no}/{len(files)} 个分片")
    return ScanResult(sorted((v[1] for v in seen.values()), key=lambda ex: ex.start_ms, reverse=True),
                      len(files), duplicates, warnings)


def _gcj_delta(lat, lon):
    x, y = lon - 105, lat - 35
    a = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*math.sqrt(abs(x))
    b = 300 + x + 2*y + .1*x*x + .1*x*y + .1*math.sqrt(abs(x))
    common = (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    a += common + (20*math.sin(y*math.pi) + 40*math.sin(y*math.pi/3))*2/3
    a += (160*math.sin(y*math.pi/12) + 320*math.sin(y*math.pi/30))*2/3
    b += common + (20*math.sin(x*math.pi) + 40*math.sin(x*math.pi/3))*2/3
    b += (150*math.sin(x*math.pi/12) + 300*math.sin(x*math.pi/30))*2/3
    rad = math.radians(lat)
    magic = 1 - .006693421622965943 * math.sin(rad)**2
    return (a*180/((6378245*(1-.006693421622965943))/(magic**1.5)*math.pi),
            b*180/(6378245/math.sqrt(magic)*math.cos(rad)*math.pi))


def gcj_to_wgs(lat, lon):
    if not (72.004 <= lon <= 137.8347 and .8293 <= lat <= 55.8271):
        return lat, lon
    guess_lat, guess_lon = lat, lon
    for _ in range(5):
        dlat, dlon = _gcj_delta(guess_lat, guess_lon)
        guess_lat -= guess_lat + dlat - lat
        guess_lon -= guess_lon + dlon - lon
    return guess_lat, guess_lon


def _sample_second(value, start):
    value = number(value)
    if value is None:
        return None
    if value > 1e11:
        value /= 1000
    elif value < 1e9:
        value += start
    return int(value)


def build_messages(raw: dict, coord_mode="auto"):
    """No interpolation, fabricated pause boundaries, or invented distance curves."""
    if coord_mode not in COORD_MODES:
        raise ValueError("未知坐标选项")
    from garmin_fit_sdk import Profile
    summary = object_json(raw.get("summaryData", {}))
    start, end = int(raw["startTime"]) // 1000, int(raw["endTime"]) // 1000
    elapsed = (int(raw["endTime"]) - int(raw["startTime"])) / 1000
    active = number(summary.get("totalTime"))
    if active is None or active < 0 or end < start or start <= FIT_EPOCH:
        raise ValueError("无效的开始、结束时间或运动时长")
    active /= 1000
    if active > elapsed + 1:
        raise ValueError("运动时长大于开始至结束的总时长")
    active = min(active, elapsed)
    offset = offset_seconds(raw["timeZone"])
    code = int(summary.get("sportType", 9999))
    title, sport, subsport, _ = SPORTS.get(code, (f"其他运动 ({code})", "generic", "generic", "other"))
    notes = []
    if code not in SPORTS:
        notes.append(f"运动类型 {code} 以通用运动导出")
    # Some FIT profiles do not have a badminton sub-sport; keep the sport name.
    if subsport not in Profile["types"]["sub_sport"].values():
        subsport = "generic"
        notes.append("FIT 标准子类型无对应值，运动名称保留在 sport 消息中")
    paused = elapsed - active > 5
    if paused:
        notes.append("保留华为运动时长及总时长；源数据无明确暂停事件，未推测暂停边界。相对时间速度序列未导出")
    coord = str(summary.get("coordinate", "")).upper().replace("-", "")
    convert = coord_mode == "gcj02" or (coord_mode == "auto" and coord == "GCJ02")
    if coord_mode == "auto" and not coord and summary.get("vendor") == "AMAP":
        convert = True
        notes.append("源数据未明确坐标系；按高德来源假设为 GCJ-02 并转换，请试导入核对轨迹")
    elif coord_mode == "auto" and coord not in ("GCJ02", "WGS84"):
        notes.append("坐标系未知，GPS 未导出；可在界面明确指定坐标系后重新导出")
    allow_gps = coord_mode != "omit" and (coord_mode != "auto" or convert or coord == "WGS84")
    records = {}
    rejected = 0
    gps_count = 0
    leg_sport = sport in ("running", "walking", "hiking")
    def put(sec, values):
        nonlocal rejected
        if sec is None or not start <= sec <= end:
            rejected += 1
            return
        if values:
            records.setdefault(sec, {}).update(values)
    for item in detail_lines(raw.get("detailData")):
        tag = item["tp"]
        value = number(item.get("v"))
        if tag == "lbs" and allow_gps:
            position = _gps_position(item)
            sec = _sample_second(item.get("t"), start)
            if position is None or sec is None or not start <= sec <= end:
                rejected += 1
                continue
            lat, lon = position
            if convert:
                lat, lon = gcj_to_wgs(lat, lon)
            put(sec, {"position_lat": round(lat * 2**31 / 180),
                      "position_long": round(lon * 2**31 / 180)})
            gps_count += 1
            # lbs.alt is commonly zero-filled. Use timestamped alti/alt instead.
        elif tag in ("h-r", "i-h-r") and value is not None and 0 < value < 255:
            sec = _sample_second(item.get("k"), start)
            if tag == "i-h-r" and sec in records and "heart_rate" in records[sec]:
                continue
            put(sec, {"heart_rate": round(value)})
        elif tag == "s-r" and leg_sport and value is not None and 0 <= value <= 500:
            cadence = value / 2
            put(_sample_second(item.get("k"), start),
                {"cadence": int(cadence), "fractional_cadence": cadence % 1})
        elif tag in ("alti", "alt") and value is not None and -500 <= value <= 20000:
            put(_sample_second(item.get("k"), start), {"enhanced_altitude": value})
        elif tag == "rs" and not paused and value is not None and 0 <= value < 1000:
            put(_sample_second(item.get("k"), start), {"enhanced_speed": value / 10})
    if not gps_count:
        notes.append("无 GPS 轨迹导出；保留现有传感器记录与汇总")
    if rejected:
        notes.append(f"忽略 {rejected} 个无效坐标或超出运动时间范围的采样")
    if not records:
        raise ValueError("没有可用的带时间传感器采样，无法生成运动 FIT")
    # FIT distance is a summary only: the archive has no documented cumulative
    # distance channel. Do not manufacture one by distributing the total.
    fields = {"start_time": start - FIT_EPOCH, "timestamp": end - FIT_EPOCH,
              "total_elapsed_time": elapsed, "total_timer_time": active}
    distance = number(summary.get("totalDistance"))
    if distance is not None and distance >= 0:
        fields["total_distance"] = distance
    calories = number(summary.get("totalCalories"))
    if calories is not None and 0 <= calories / 1000 < 65535:
        fields["total_calories"] = round(calories / 1000)
    for src, dest in (("avgHeartRate", "avg_heart_rate"), ("maxHeartRate", "max_heart_rate")):
        v = number(summary.get(src))
        if v is not None and 0 < v < 255:
            fields[dest] = round(v)
    for src, dest in (("creepingWave", "total_ascent"), ("mTotalDescent", "total_descent")):
        v = number(summary.get(src))
        if v is not None and 0 <= v / 10 < 65535:
            fields[dest] = round(v / 10)
    if active > 0 and distance is not None and distance > 0:
        fields["enhanced_avg_speed"] = distance / active
    if leg_sport:
        for src, dest in (("avgStepRate", "avg_cadence"), ("bestStepRate", "max_cadence")):
            v = number(summary.get(src))
            if v is not None and 0 <= v <= 500:
                fields[dest] = int(v / 2)
                fields[dest.replace("_cadence", "_fractional_cadence")] = (v / 2) % 1
        steps = number(summary.get("totalSteps"))
        if steps is not None and steps >= 0:
            fields["total_cycles"] = int(steps / 2)
            fields["total_fractional_cycles"] = (steps / 2) % 1
    messages = []
    def message(message_type, **values):
        messages.append({"mesg_num": Profile["mesg_num"][message_type], **values})
    message("FILE_ID", type="activity", manufacturer="development", product=1,
            time_created=start - FIT_EPOCH)
    message("DEVICE_INFO", timestamp=start - FIT_EPOCH, device_index="creator",
            manufacturer="development", product=1, product_name="Huawei Health JSON Converter")
    message("SPORT", sport=sport, sub_sport=subsport, name=title)
    message("EVENT", timestamp=start - FIT_EPOCH, event="timer", event_type="start")
    for sec, values in sorted(records.items()):
        message("RECORD", timestamp=sec - FIT_EPOCH, **values)
    message("EVENT", timestamp=end - FIT_EPOCH, event="timer", event_type="stop_all")
    message("LAP", message_index=0, event="lap", event_type="stop", **fields)
    message("SESSION", message_index=0, sport=sport, sub_sport=subsport,
            first_lap_index=0, num_laps=1, **fields)
    message("ACTIVITY", timestamp=end - FIT_EPOCH, total_timer_time=active, num_sessions=1,
            type="manual", event="activity", event_type="stop",
            local_timestamp=end - FIT_EPOCH + offset)
    notes.append("本版本导出一个汇总圈；原始分公里、分英里配速未重建为独立圈")
    return messages, list(dict.fromkeys(notes))


def encode_fit(raw, coord_mode="auto"):
    from garmin_fit_sdk import Encoder
    messages, notes = build_messages(raw, coord_mode)
    encoder = Encoder()
    for message in messages:
        encoder.write_mesg(message)
    data = bytes(encoder.close())
    validate_fit(data)
    return data, notes


def validate_fit(data: bytes):
    from garmin_fit_sdk import Decoder, Stream
    if not Decoder(Stream.from_byte_array(bytearray(data))).check_integrity():
        raise ValueError("FIT 文件长度或 CRC 校验失败")
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    if errors:
        raise ValueError(f"FIT 解码失败：{errors}")
    for name in ("file_id_mesgs", "session_mesgs", "lap_mesgs", "activity_mesgs", "record_mesgs"):
        if not messages.get(name):
            raise ValueError(f"FIT 缺少必要消息：{name}")
    return messages


def atomic_bytes(path: Path, data: bytes):
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".huawei-fit-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def write_json(path, data):
    atomic_bytes(Path(path), json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def package_fit_files(files: list[Path], output: Path, cancel: Event | None = None,
                      progress: Callable | None = None, max_bytes=ZIP_MAX_BYTES):
    """Create flat, FIT-only ZIPs within both compressed and raw size limits."""
    files = list(dict.fromkeys(Path(file).resolve() for file in files))
    if not files:
        raise ValueError("没有成功导出的 FIT，无法创建 ZIP 包")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    groups, group, estimate = [], [], 22
    names = set()
    for path in files:
        if cancel and cancel.is_set():
            raise InterruptedError("已取消 ZIP 打包")
        if path.suffix.lower() != ".fit" or not path.is_file():
            raise ValueError(f"不是可用的 FIT 文件：{path.name}")
        if path.name.casefold() in names:
            raise ValueError(f"ZIP 内存在同名 FIT：{path.name}")
        names.add(path.name.casefold())
        size = path.stat().st_size
        # Conservative bound for DEFLATE expansion plus both ZIP headers.
        bound = size + ((size + 999) // 1000) * 8 + 256 + 2 * len(path.name.encode("utf-8"))
        if bound + 22 > max_bytes:
            raise ValueError(f"单个 FIT 超过 ZIP 分包大小限制：{path.name}")
        if group and estimate + bound > max_bytes:
            groups.append(group)
            group, estimate = [], 22
        group.append(path)
        estimate += bound
    if group:
        groups.append(group)
    base = f"Zepp_FIT_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    pending, published, archives = [], [], []
    completed = 0
    try:
        for part, paths in enumerate(groups, 1):
            if cancel and cancel.is_set():
                raise InterruptedError("已取消 ZIP 打包")
            handle, temp_name = tempfile.mkstemp(dir=output, prefix=".huawei-fit-zip-", suffix=".tmp")
            os.close(handle)
            temp = Path(temp_name)
            name = f"{base}.zip" if len(groups) == 1 else f"{base}_part{part:02}.zip"
            destination = output / name
            pending.append((temp, destination))
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=False) as archive:
                for path in paths:
                    if cancel and cancel.is_set():
                        raise InterruptedError("已取消 ZIP 打包")
                    archive.write(path, arcname=path.name)
                    completed += 1
                    if progress:
                        progress(completed, len(files), f"正在打包 ZIP {completed}/{len(files)}")
            with zipfile.ZipFile(temp) as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP 文件完整性校验失败")
                raw_size = sum(item.file_size for item in archive.infolist())
            if temp.stat().st_size > max_bytes or raw_size > max_bytes:
                raise ValueError("ZIP 超出大小限制，未发布压缩包")
            archives.append({"file": str(destination), "count": len(paths),
                             "bytes": temp.stat().st_size, "uncompressed_bytes": raw_size})
        if cancel and cancel.is_set():
            raise InterruptedError("已取消 ZIP 打包")
        for temp, destination in pending:
            # UUID names and exclusive reservation prevent replacing an existing ZIP.
            with destination.open("xb"):
                pass
            published.append(destination)
            os.replace(temp, destination)
        return archives
    except BaseException:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        for temp, _ in pending:
            temp.unlink(missing_ok=True)


def export_exercises(exercises: list[Exercise], output: Path, coord_mode="auto",
                     cancel: Event | None = None, progress: Callable | None = None,
                     pack_zip=False, zip_progress: Callable | None = None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "export_manifest.json"
    try:
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
        if not isinstance(manifest, dict):
            raise ValueError("格式无效")
    except (ValueError, OSError) as exc:
        raise ValueError(f"无法读取已有导出清单，请选择新目录：{exc}") from exc
    outcomes = []
    cached_path, cached_data = None, None
    for index, exercise in enumerate(exercises, 1):
        if cancel and cancel.is_set():
            break
        result = {"record_id": exercise.record_id, "date": exercise.local_start.isoformat(),
                  "sport": exercise.sport[0], "source": str(exercise.source), "status": "failed"}
        try:
            if cached_path != exercise.source:
                cached_data = read_json(exercise.source)
                cached_path = exercise.source
            raw = cached_data[exercise.index]
            if (str(raw.get("recordId") or "") != exercise.record_id
                    or int(raw["startTime"]) != exercise.start_ms):
                raise ValueError("扫描后源文件已改变，请重新扫描")
            fingerprint = hashlib.sha256(json.dumps({"raw": raw, "mode": coord_mode, "version": FIT_FORMAT_VERSION},
                                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            known = manifest.get(fingerprint, {})
            known_name = known.get("file", "")
            known_path = output / known_name
            if known_name and Path(known_name).name == known_name and known_path.is_file():
                existing = known_path.read_bytes()
                if hashlib.sha256(existing).hexdigest() == known.get("sha256"):
                    validate_fit(existing)
                    result.update(status="skipped", file=str(known_path), notes=known.get("notes", []))
                    outcomes.append(result)
                    if progress:
                        progress(index, len(exercises), result)
                    continue
            data, notes = encode_fit(raw, coord_mode)
            filename = f"{exercise.local_start:%Y-%m-%d_%H%M%S}_{exercise.sport[3]}_{fingerprint[:10]}.fit"
            path = output / filename
            if path.exists():
                if path.read_bytes() != data:
                    path = output / f"{path.stem}_{uuid.uuid4().hex[:6]}.fit"
                else:
                    result["status"] = "skipped"
            if result["status"] != "skipped":
                atomic_bytes(path, data)
                result["status"] = "success"
            manifest[fingerprint] = {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(),
                                     "record_id": exercise.record_id, "notes": notes}
            write_json(manifest_path, manifest)
            result.update(file=str(path), notes=list(dict.fromkeys(exercise.notes + notes)))
        except Exception as exc:
            result.update(error=f"{type(exc).__name__}: {exc}")
        outcomes.append(result)
        if progress:
            progress(index, len(exercises), result)
    report = {"version": VERSION, "coordinate_mode": coord_mode,
              "created_at": datetime.now().astimezone().isoformat(), "requested": len(exercises),
              "cancelled": bool(cancel and cancel.is_set()),
              "success": sum(x["status"] == "success" for x in outcomes),
              "skipped": sum(x["status"] == "skipped" for x in outcomes),
              "failed": sum(x["status"] == "failed" for x in outcomes), "results": outcomes}
    if pack_zip:
        report["zip_files"] = []
        if not report["cancelled"]:
            try:
                files = [Path(item["file"]) for item in outcomes if item["status"] in ("success", "skipped")]
                report["zip_files"] = package_fit_files(files, output, cancel, zip_progress)
            except InterruptedError:
                report["cancelled"] = True
            except Exception as exc:
                report["zip_error"] = f"{type(exc).__name__}: {exc}"
    report_path = output / f"conversion_report_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:4]}.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def sample_exercises(exercises):
    """Pick distinct GPS, significant pause and no-GPS examples."""
    selected = []
    for predicate in (lambda x: x.gps_points > 0,
                      lambda x: (x.end_ms - x.start_ms)/1000 - x.duration > 30,
                      lambda x: x.gps_points == 0):
        candidate = next((x for x in exercises if predicate(x) and x not in selected), None)
        if candidate:
            selected.append(candidate)
    return selected
