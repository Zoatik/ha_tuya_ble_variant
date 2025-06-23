def build_timer_raw(
    hour: int,
    minute: int,
    duration_minutes: int,
    days: list[str],
    enabled: bool
) -> bytes:
    """
    Construit la séquence RAW pour le timer.
    """
    day_bits = {
        "sun": 0x01, "mon": 0x02, "tue": 0x04, "wed": 0x08,
        "thu": 0x10, "fri": 0x20, "sat": 0x40,
    }
    mask = 0
    for day in days:
        mask |= day_bits[day.lower()[:3]]
    total_minutes = hour * 60 + minute
    hhmm = total_minutes.to_bytes(2, "big")
    dddd = duration_minutes.to_bytes(2, "big")
    raw = bytearray()
    raw.append(0x01)
    raw.append(0x01)
    raw.extend(hhmm)
    raw.extend(dddd)
    raw.append(mask)
    raw.append(0x64)
    raw.append(0x01 if enabled else 0x00)
    raw.append(0x07)
    raw.extend(b"\xE9\x06")
    raw.append(0x14)
    raw.append(0x01)
    return bytes(raw)

def parse_timer_raw(raw: bytes):
    """
    Décode la séquence RAW du timer.
    """
    if not raw or len(raw) < 14:
        return None
    total_minutes = int.from_bytes(raw[2:4], "big")
    hour = total_minutes // 60
    minute = total_minutes % 60
    duration = int.from_bytes(raw[4:6], "big")
    mask = raw[6]
    enabled = raw[8] == 0x01
    days = []
    day_names = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
    for i, name in enumerate(day_names):
        if mask & (1 << i):
            days.append(name)
    return {
        "hour": hour,
        "minute": minute,
        "duration": duration,
        "days": days,
        "enabled": enabled,
    }

def set_timer_param(self, param: str, value: int):
    """
    Modifie un paramètre (hour, minute, duration) du timer et envoie la nouvelle valeur RAW.
    """
    datapoint = self._device.datapoints[17]
    if datapoint and isinstance(datapoint.value, bytes):
        parsed = parse_timer_raw(datapoint.value)
        if parsed is not None:
            parsed[param] = value
            raw = build_timer_raw(
                hour=parsed["hour"],
                minute=parsed["minute"],
                duration_minutes=parsed["duration"],
                days=parsed["days"],
                enabled=parsed["enabled"]
            )
            self._hass.create_task(datapoint.set_value(raw))

def set_timer_day(self, day: str, value: bool):
    """
    Active ou désactive un jour dans la programmation du timer et envoie la nouvelle valeur RAW.
    """
    datapoint = self._device.datapoints[17]
    if datapoint and isinstance(datapoint.value, bytes):
        parsed = parse_timer_raw(datapoint.value)
        if parsed is not None:
            days = set(parsed["days"])
            if value:
                days.add(day)
            else:
                days.discard(day)
            raw = build_timer_raw(
                hour=parsed["hour"],
                minute=parsed["minute"],
                duration_minutes=parsed["duration"],
                days=list(days),
                enabled=parsed["enabled"]
            )
            self._hass.create_task(datapoint.set_value(raw))