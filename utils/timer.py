from datetime import datetime, timedelta


def seconds_remaining(start_time_iso: str, minutes_allowed: int) -> int:
    start = datetime.fromisoformat(start_time_iso)
    end = start + timedelta(minutes=minutes_allowed)
    remaining = (end - datetime.now()).total_seconds()
    return max(0, int(remaining))


def format_hms(total_seconds: int) -> str:
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
