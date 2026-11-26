from bisect import bisect_left
from datetime import datetime
from pathlib import PurePosixPath

from PIL import ExifTags, Image
from pydantic import BaseModel, ConfigDict

from app.schemas.survey_result import Identifier, Located


class PhotoLocation(Located):
    model_config = ConfigDict(extra="forbid")
    frame_id: Identifier
    captured_at: datetime | None = None


class CoordinateFile(BaseModel):
    frames: list[PhotoLocation]


def coordinate(values, ref, directions, maximum):
    if isinstance(ref, bytes):
        ref = ref.decode("ascii")
    if ref not in directions or len(values) != 3:
        raise ValueError("Invalid EXIF GPS")
    degrees, minutes, seconds = map(float, values)
    result = degrees + minutes / 60 + seconds / 3600
    if not (0 <= minutes < 60 and 0 <= seconds < 60 and 0 <= result <= maximum):
        raise ValueError("Invalid EXIF GPS")
    return -result if ref == directions[1] else result


def photo_metadata(path):
    fields = {}
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            details = exif.get_ifd(ExifTags.IFD.Exif)
            stamp = details.get(36867) or exif.get(36867) or exif.get(306)
            offset = details.get(36881, "")
            if stamp:
                try:
                    captured = datetime.strptime(stamp, "%Y:%m:%d %H:%M:%S")
                    fields["captured_at"] = datetime.fromisoformat(
                        captured.isoformat() + offset
                    ).isoformat()
                except (ValueError, TypeError):
                    pass
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if gps:
                if (
                    gps.get(29)
                    and gps.get(7)
                    and not (
                        fields.get("captured_at")
                        and datetime.fromisoformat(fields["captured_at"]).tzinfo
                    )
                ):
                    hour, minute, second = map(float, gps[7])
                    day = datetime.strptime(gps[29], "%Y:%m:%d").date()
                    fields["captured_at"] = (
                        f"{day.isoformat()}T{int(hour):02d}:{int(minute):02d}:{int(second):02d}+00:00"
                    )
                lat = coordinate(gps[2], gps[1], ("N", "S"), 90)
                lon = coordinate(gps[4], gps[3], ("E", "W"), 180)
                fields.update(lat=lat, lon=lon, location_source="exif")
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ZeroDivisionError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ):
        # Optional EXIF may be absent or unreadable even on a usable image.
        pass
    return fields


def image_path_index(inputs):
    names = {}
    suffixes = {}
    for item in inputs:
        if item["kind"] != "image":
            continue
        name = item["name"]
        names[name] = item
        parts = PurePosixPath(name).parts
        for start in range(1, len(parts)):
            suffix = "/".join(parts[start:])
            suffixes[suffix] = None if suffix in suffixes else item
    return {**suffixes, **names}


def apply_coordinate_file(inputs, sidecars):
    files = [
        path
        for path in sidecars
        if PurePosixPath(path).name.lower() == "coordinates.json"
    ]
    if len(files) > 1:
        raise ValueError("Нужен один файл coordinates.json")
    if not files:
        return
    metadata = CoordinateFile.model_validate_json(sidecars.pop(files[0]))
    index = image_path_index(inputs)
    seen = set()
    for frame in metadata.frames:
        item = index.get(frame.frame_id)
        if not item or item["id"] in seen:
            raise ValueError(
                f"Неоднозначная или отсутствующая фотография {frame.frame_id}"
            )
        seen.add(item["id"])
        if frame.lat is not None:
            item["location_source"] = "coordinates"
        item.update(
            frame.model_dump(mode="json", exclude={"frame_id"}, exclude_none=True)
        )


def locate_from_track(inputs, fixes):
    if not fixes:
        return
    locations = {}
    for stamp, lat, lon in fixes:
        previous = locations.setdefault(stamp, (lat, lon))
        if previous != (lat, lon):
            locations[stamp] = None
    times = sorted(locations)
    for item in inputs:
        if (
            item["kind"] != "image"
            or item.get("lat") is not None
            or not item.get("captured_at")
        ):
            continue
        captured = datetime.fromisoformat(item["captured_at"])
        if captured.tzinfo is None:
            continue
        stamp = captured.timestamp()
        pos = bisect_left(times, stamp)
        candidates = times[max(0, pos - 1) : pos + 1]
        nearest = min(candidates, key=lambda t: abs(t - stamp))
        if abs(nearest - stamp) > 5:
            continue
        matches = {
            locations[t] for t in candidates if abs(t - stamp) == abs(nearest - stamp)
        }
        if len(matches) == 1 and None not in matches:
            lat, lon = matches.pop()
            item.update(lat=lat, lon=lon, location_source="gpx")
