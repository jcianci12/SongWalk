from __future__ import annotations

from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError, POPM, TALB, TIT2, TPE1


WMP_POPM_EMAIL = "Windows Media Player 9 Series"
STAR_TO_POPM = {
    0: 0,
    1: 1,
    2: 64,
    3: 128,
    4: 196,
    5: 255,
}


def read_mp3_metadata(file_path: Path) -> dict[str, int | str]:
    if Path(file_path).suffix.lower() != ".mp3":
        return {}

    try:
        tags = ID3(file_path)
    except ID3NoHeaderError:
        return {}
    except Exception:
        return {}

    return {
        "title": _text_value(tags, "TIT2"),
        "artist": _text_value(tags, "TPE1"),
        "album": _text_value(tags, "TALB"),
        "rating": _read_rating(tags),
    }


def write_mp3_metadata(file_path: Path, *, title: str, artist: str, album: str, rating: int) -> None:
    if Path(file_path).suffix.lower() != ".mp3":
        return

    try:
        tags = ID3(file_path)
    except Exception:
        tags = ID3()

    _set_text_frame(tags, "TIT2", TIT2, title)
    _set_text_frame(tags, "TPE1", TPE1, artist)
    _set_text_frame(tags, "TALB", TALB, album)
    _set_rating(tags, rating)
    tags.save(file_path, v2_version=3)


def clamp_rating(value: int | str | None) -> int:
    try:
        numeric = int(value or 0)
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(5, numeric))


def _text_value(tags: ID3, key: str) -> str:
    frame = tags.get(key)
    if not frame or not getattr(frame, "text", None):
        return ""
    return str(frame.text[0]).strip()


def _set_text_frame(tags: ID3, key: str, frame_class, value: str) -> None:
    clean_value = value.strip()
    if clean_value:
        tags.setall(key, [frame_class(encoding=3, text=[clean_value])])
    else:
        tags.delall(key)


def _read_rating(tags: ID3) -> int:
    popm_frames = tags.getall("POPM")
    if not popm_frames:
        return 0

    preferred = next((frame for frame in popm_frames if getattr(frame, "email", "") == WMP_POPM_EMAIL), popm_frames[0])
    return _stars_from_popm_value(int(getattr(preferred, "rating", 0) or 0))


def _set_rating(tags: ID3, rating: int) -> None:
    remaining_frames = [frame for frame in tags.getall("POPM") if getattr(frame, "email", "") != WMP_POPM_EMAIL]
    stars = clamp_rating(rating)
    if stars:
        remaining_frames.append(POPM(email=WMP_POPM_EMAIL, rating=STAR_TO_POPM[stars], count=0))
    tags.setall("POPM", remaining_frames)


def _stars_from_popm_value(value: int) -> int:
    if value >= 224:
        return 5
    if value >= 160:
        return 4
    if value >= 96:
        return 3
    if value >= 32:
        return 2
    if value >= 1:
        return 1
    return 0
