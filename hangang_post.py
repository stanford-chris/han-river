#!/usr/bin/env python3
"""
Post a "Han River right now" snapshot to Bluesky.

v1 (text/data only, no image): the current air temperature and conditions
(Open-Meteo) alongside the live Han River water temperature (Seoul Open Data,
dataset OA-15488, station Seonyu on the main stem), plus a seasonal note whose
hook is the water-vs-air contrast.

Data sources (both CC BY, credited in the post):
  - Water temp: Seoul Open Data Plaza, service WPOSInformationTime
  - Air/weather: Open-Meteo

Curly quotes in post text are written as \\u2019 escapes: the editing tools
mangle literal curly quotes in Python source (see the Sherlock bot notes), so
the escape keeps the source safe to edit while the runtime output still renders
the real character. Other non-ASCII (Korean, emoji, degree sign) is fine as a
literal.

Requires (for actual posting, not --dry-run):
  - hangang_config.json with {"api_key": "...", "handle": "<bot>.bsky.social"}
  - the bot's Bluesky app password in the Keychain:
      security add-generic-password -a "<bot>.bsky.social" -s "hanriver-bluesky" -w

Usage:
  python3 hangang_post.py            # launchd entry: posts only when a random daily slot is due
  python3 hangang_post.py --now      # post one snapshot immediately (manual)
  python3 hangang_post.py --dry-run  # compose and print without posting
"""

import json
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from atproto import Client, client_utils

import net_guard

HERE = Path(__file__).parent
CONFIG = HERE / 'hangang_config.json'
STATE = HERE / 'hangang_state.json'
KEYCHAIN_SERVICE = 'hanriver-bluesky'

# Refuse anything unrecognised before the flags below are read. Bare membership
# tests silently ignore what they do not recognise, so a typo (`--dryrun`) or a
# reflex (`--help`) reads as neither flag and takes the ordinary scheduled
# path, which posts. seoul-index published a real thread that way on 20 July
# 2026; this bot is not live yet, so it gets the guard before it ever can.
_KNOWN_ARGS = {'--dry-run', '--now'}

if __name__ == '__main__':
    _unknown = [a for a in sys.argv[1:] if a not in _KNOWN_ARGS]
    if _unknown:
        sys.exit(f'Unknown argument(s): {" ".join(_unknown)}. '
                 f'Recognised: {" ".join(sorted(_KNOWN_ARGS))}. '
                 f'Refusing to run (a bare run posts live).')

DRY_RUN = '--dry-run' in sys.argv
FORCE = '--now' in sys.argv  # post immediately, ignoring the random schedule

MAX_POST_CHARS = 290  # buffer under Bluesky's 300-grapheme limit
SEOUL_TZ = ZoneInfo('Asia/Seoul')

# Han River water-quality dataset OA-15488, service WPOSInformationTime. Rows
# come newest-first, hourly. Station "Seonyu" (선유) sits on the Han main stem
# near Seonyudo / Yanghwa Bridge; the other three stations (Tancheon,
# Jungnangcheon, Anyangcheon) are tributaries, so Seonyu is the one that reads
# as "the Han River".
WATER_API = 'http://openapi.seoul.go.kr:8088/{key}/json/WPOSInformationTime/1/50/'
WATER_SOURCE_URL = 'https://data.seoul.go.kr/dataList/OA-15488/S/1/datasetView.do'
HAN_STATION = '선유'  # 선유 (Seonyu)

# Han riverside coordinate (by Seonyudo) for the air reading.
AIR_LAT, AIR_LON = 37.543, 126.897
AIR_API = (
    'https://api.open-meteo.com/v1/forecast'
    '?latitude={lat}&longitude={lon}'
    '&current=temperature_2m,apparent_temperature,weather_code,relative_humidity_2m,wind_speed_10m'
    '&timezone=Asia%2FSeoul'
)

# 한강홍수통제소 (HRFCO) — Jamsu Bridge (잠수교) water-level gauge, station 1018680.
HRFCO_RANGE = 'http://api.hrfco.go.kr/{key}/waterlevel/list/10M/{obs}/{s}/{e}.json'
HRFCO_FLDFCT = 'http://api.hrfco.go.kr/{key}/fldfct/list.json'
HRFCO_SOURCE_URL = 'https://www.hrfco.go.kr/'
JAMSU_OBS = '1018680'
# Jamsu Bridge flood-warning thresholds (metres), from HRFCO waterlevel/info,
# verified 2026-07-18. Official static levels; update if HRFCO revises them.
# Highest first: (level, plain-English status); below the lowest -> 'normal'.
JAMSU_LEVELS = [(6.5, 'flood alert', '심각'), (6.2, 'very high', '경계'),
                (5.5, 'high', '주의'), (3.9, 'running high', '관심')]

# WMO weather interpretation codes -> concise condition word.
WMO = {
    0: 'clear', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast',
    45: 'fog', 48: 'freezing fog',
    51: 'light drizzle', 53: 'drizzle', 55: 'heavy drizzle',
    56: 'freezing drizzle', 57: 'freezing drizzle',
    61: 'light rain', 63: 'rain', 65: 'heavy rain',
    66: 'freezing rain', 67: 'freezing rain',
    71: 'light snow', 73: 'snow', 75: 'heavy snow', 77: 'snow grains',
    80: 'showers', 81: 'showers', 82: 'heavy showers',
    85: 'snow showers', 86: 'snow showers',
    95: 'thunderstorm', 96: 'thunderstorm', 99: 'thunderstorm',
}

# (#tag display, facet value). '한강' = 한강.
TAGS = [('한강', '한강'), ('HanRiver', 'hanriver'), ('Seoul', 'seoul')]


def http_get_json(url):
    """GET a URL and parse JSON, via curl.

    Homebrew Python 3.13's urllib fails HTTPS cert verification on this machine,
    so shelling out to curl keeps both the HTTP (Seoul) and HTTPS (Open-Meteo)
    fetches uniform and reliable.
    """
    result = subprocess.run(
        ['curl', '-s', '--max-time', '30', url],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f'Request failed: {url}\n{result.stderr.strip()}')
    return json.loads(result.stdout)


def keychain_password(account, service):
    result = subprocess.run(
        ['security', 'find-generic-password', '-a', account, '-s', service, '-w'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'No Keychain password for account="{account}" service="{service}".\n'
            f'Add it with:\n'
            f'  security add-generic-password -a "{account}" -s "{service}" -w'
        )
    return result.stdout.strip()


def water_temp(api_key):
    """Latest valid water temperature (C) at the Seonyu main-stem station.

    Returns (temp_float, 'YYYYMMDD', 'HH:MM'). Walks back through the hourly
    rows, skipping any that read '점검중' (under maintenance) or are blank, so a
    sensor outage doesn't take the bot down.
    """
    data = http_get_json(WATER_API.format(key=api_key))
    rows = data['WPOSInformationTime']['row']
    for row in rows:
        if row.get('MSRSTN_NM') != HAN_STATION:
            continue
        raw = (row.get('WATT') or '').strip()
        try:
            return float(raw), row.get('YMD', ''), row.get('HR', '')
        except ValueError:
            continue  # maintenance / blank — try the previous hour
    raise RuntimeError('No valid Seonyu water temperature in the latest rows.')


def air_now():
    data = http_get_json(AIR_API.format(lat=AIR_LAT, lon=AIR_LON))
    cur = data['current']
    return (float(cur['temperature_2m']),
            float(cur['apparent_temperature']),
            WMO.get(int(cur['weather_code']), 'cloudy'))


def water_level(hrfco_key, now):
    """Latest Jamsu Bridge (잠수교) level in metres + a plain-English status.

    Returns (level_m, status, arrow), or None on any failure so a HRFCO outage drops
    just the level line rather than taking down the whole post.
    """
    try:
        base = now.replace(minute=now.minute // 10 * 10, second=0, microsecond=0)
        end = base.strftime('%Y%m%d%H%M')
        start = (base - timedelta(hours=2)).strftime('%Y%m%d%H%M')
        data = http_get_json(HRFCO_RANGE.format(key=hrfco_key, obs=JAMSU_OBS, s=start, e=end))
        pts = [(r['ymdhm'], float(str(r.get('wl', '')).strip()))
               for r in (data.get('content') or []) if str(r.get('wl', '')).strip()]
        if not pts:
            return None
        pts.sort()
        latest_t, wl = pts[-1]
    except (RuntimeError, KeyError, ValueError, TypeError):
        return None
    status = 'normal'
    for level, label, kor in JAMSU_LEVELS:
        if wl >= level:
            status = f'{label} ({kor})'
            break

    arrow = ''
    latest_dt = datetime.strptime(latest_t, '%Y%m%d%H%M')
    older = [p for p in pts
             if datetime.strptime(p[0], '%Y%m%d%H%M') <= latest_dt - timedelta(minutes=40)]
    if older:
        target = latest_dt - timedelta(minutes=60)
        prev = min(older, key=lambda p: abs(
            (datetime.strptime(p[0], '%Y%m%d%H%M') - target).total_seconds()))
        delta = wl - prev[1]
        arrow = '\u2191' if delta > 0.02 else '\u2193' if delta < -0.02 else '\u2192'
    return wl, status, arrow


def flood_advisory(hrfco_key):
    """Active Seoul flood advisory/warning text for the post, or None.

    HRFCO fldfct/list carries issue ('발령') and lift ('해제') notices across the
    Han basin. Per station the most recent notice wins: a '발령' is still active.
    Kept to Seoul stations (obsnm starting '서울시', which includes the main-Han
    forecast point 한강대교); silent when nothing is active.
    """
    try:
        rows = http_get_json(HRFCO_FLDFCT.format(key=hrfco_key)).get('content') or []
    except (RuntimeError, KeyError, TypeError):
        return None
    latest = {}
    for r in rows:
        code = r.get('sttnm')
        if code and r.get('ancdt', '') >= latest.get(code, {}).get('ancdt', ''):
            latest[code] = r
    active = [r for r in latest.values()
              if '발령' in r.get('kind', '')
              and str(r.get('obsnm', '')).startswith('서울시')]
    if not active:
        return None
    rivers = list(dict.fromkeys(r.get('rvrnm') or r.get('obsnm') for r in active))
    kind = 'warning' if any('경보' in r.get('kind', '') for r in active) else 'advisory'
    return f'Flood {kind}: ' + ', '.join(rivers)


def seasonal_note(now, water, air):
    """One-line note: a seasonal phrase plus the water-vs-air contrast.

    '\\u2019' renders as a curly apostrophe. The capital after the colon follows
    the house style (a full sentence after a colon is capitalised).
    """
    m = now.month
    if m in (12, 1, 2):
        phrase = 'Deep midwinter'
    elif m in (3, 4, 5):
        phrase = 'Spring on the riverbank'
    elif m == 6:
        phrase = 'Early summer on the Han'
    elif m == 7:
        phrase = 'Peak 장마 season'  # 장마 (the summer monsoon)
    elif m == 8:
        phrase = 'High summer on the Han'
    else:
        phrase = 'Autumn on the river'

    if water - air >= 1:
        clause = 'The river\u2019s warmer than the air.'
    elif air - water >= 1:
        clause = 'The air\u2019s warmer than the river.'
    else:
        clause = 'Air and water hold about even.'
    return f'{phrase}: {clause}'


def fmt(t):
    """25.4 -> '25.4', 25.0 -> '25', -3.0 -> '-3'."""
    return f'{t:.1f}'.rstrip('0').rstrip('.')


def build_post(water, air, feels, cond, level, flood, note):
    # Reading-line emoji: \U0001f321 thermometer, \U0001f4a7 droplet.
    reading = (
        f'\U0001f321️ Air {fmt(air)}°C (feels {fmt(feels)}°C), {cond} '
        f'· \U0001f4a7 Water {fmt(water)}°C\n'
    )
    level_line = ''
    if level is not None:
        wl, status, arrow = level
        arrow_str = f' {arrow}' if arrow else ''
        level_line = f'\U0001f4cf Level {fmt(wl)}m{arrow_str} at 잠수교 · {status}\n'
    body = f'{note}\n\n'
    flood_line = f'\u26a0\ufe0f {flood}\n\n' if flood else ''

    tb = client_utils.TextBuilder()
    tb.text(flood_line + reading + level_line + body)
    for i, (tag, label) in enumerate(TAGS):
        if i:
            tb.text(' ')
        tb.tag(f'#{tag}', label)
    tb.text('\n')
    tb.link('Seoul Open Data', WATER_SOURCE_URL)
    tb.text(' · ')
    tb.link('Open-Meteo', 'https://open-meteo.com/')
    if level is not None:
        tb.text(' · ')
        tb.link('HRFCO', HRFCO_SOURCE_URL)
    return tb


# --- Random daily schedule -------------------------------------------------
# launchd wakes this script every 15 minutes. Each day we roll SCHED_COUNT
# random post times inside a daytime window (>= SCHED_MIN_GAP apart) and store
# them in state; a wake posts once when a slot's time has arrived. Missed wakes
# (machine asleep / rebooting) self-heal: the next wake fires an overdue slot.
SCHED_WINDOW = (7 * 60, 22 * 60)  # 07:00-22:00 KST, minutes past midnight
SCHED_COUNT = 3
SCHED_MIN_GAP = 180  # >= 3h between posts


def pick_slots():
    start, end = SCHED_WINDOW
    avail = (end - start) - SCHED_MIN_GAP * (SCHED_COUNT - 1)
    offsets = sorted(random.random() * avail for _ in range(SCHED_COUNT))
    return [int(round(start + offsets[i] + i * SCHED_MIN_GAP))
            for i in range(SCHED_COUNT)]


def due_slot(now, state):
    """Return the earliest slot (minutes past midnight) that is due and unposted,
    else None. Rolls a fresh set of slots when the KST day changes; slots already
    in the past at roll time are pre-marked fired so a mid-day first run does not
    retro-post. Mutates state; the caller persists it."""
    today = now.strftime('%Y%m%d')
    now_min = now.hour * 60 + now.minute
    if state.get('sched_date') != today:
        state['sched_date'] = today
        state['slots'] = pick_slots()
        state['fired'] = [s for s in state['slots'] if s <= now_min]
    pending = [s for s in state.get('slots', [])
               if s <= now_min and s not in state.get('fired', [])]
    return min(pending) if pending else None


def main():
    if not CONFIG.exists():
        sys.exit(f'Error: {CONFIG} not found.')
    config = json.loads(CONFIG.read_text())
    api_key = config.get('api_key')
    if not api_key:
        sys.exit(f'Error: no api_key in {CONFIG}')

    # Guarded like its siblings so it starts life with the protection they
    # gained after the August 2026 outage. Fifteen minutes is a placeholder:
    # revisit it against whatever schedule the launchd job ends up using, since
    # com.chrisstanford.hangangbot is not loaded yet.
    net_guard.require_network(900)

    now = datetime.now(SEOUL_TZ)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    slot = None
    if not (DRY_RUN or FORCE):
        slot = due_slot(now, state)
        if slot is None:
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            return

    water, ymd, hr = water_temp(api_key)
    air, feels, cond = air_now()
    level = water_level(config.get('hrfco_api_key'), now)
    flood = flood_advisory(config.get('hrfco_api_key'))
    note = seasonal_note(now, water, air)

    post = build_post(water, air, feels, cond, level, flood, note)
    plain = post.build_text()
    lvl = f'{fmt(level[0])}m {level[2]} {level[1]}' if level else 'n/a'
    print(f'Water {fmt(water)}C @ Seonyu ({ymd} {hr})  |  Air {fmt(air)}C (feels {fmt(feels)}C) {cond}  |  Level {lvl}')
    print(f'\nPost ({len(plain)} chars):\n{"-" * 44}\n{plain}\n{"-" * 44}')

    if DRY_RUN:
        print('(dry run: not posting)')
        return

    handle = config.get('handle')
    if not handle:
        sys.exit('Error: no "handle" in hangang_config.json '
                 '(create the Bluesky bot account first).')
    password = keychain_password(handle, KEYCHAIN_SERVICE)
    bsky = Client()
    bsky.login(handle, password)
    bsky.send_post(text=post)
    print('Posted successfully.')

    if slot is not None:
        state.setdefault('fired', []).append(slot)
    state['last_success_at'] = datetime.now(timezone.utc).isoformat()
    state['last_water_c'] = water
    state['last_air_c'] = air
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
