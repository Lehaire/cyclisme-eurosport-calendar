#!/usr/bin/env python3
import hashlib, html, json, re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

BASE = "https://coursedujour.com/fr/day/{}/"
DAYS = 120
OUT = Path("calendar.ics")
MANUAL = Path("manual_events.json")
PARIS = ZoneInfo("Europe/Paris")

# Only broadcasters intended for the French calendar.
CHANNELS = {
    "Eurosport / HBO Max": "EUROSPORT",
    "Eurosport / Discovery+": "EUROSPORT",
    "HBO Max (EUR)": "EUROSPORT",
    "L'EquipeTV": "L'ÉQUIPE",
    "France TV": "FRANCE TV",
    "France 2": "FRANCE 2",
    "France 3": "FRANCE 3",
    "France 4": "FRANCE 4",
    "france.tv": "FRANCE TV",
}

TZ_OFFSETS = {
    "CET": 1, "CEST": 2, "UTC": 0, "GMT": 0,
    "GMT+1": 1, "GMT+2": 2, "GMT+3": 3, "GMT+4": 4,
    "GMT+5": 5, "GMT+6": 6, "GMT+7": 7, "GMT+8": 8,
    "GMT+9": 9, "EDT": -4, "EST": -5, "PDT": -7, "PST": -8,
    "EET": 2, "EEST": 3, "JST": 9,
}

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})(?:\s*[–-]\s*(\d{1,2}:\d{2}))?\s*([A-Z]{2,5}(?:[+-]\d+)?)\b")

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def normalize_title(s):
    s = clean(s)
    s = re.sub(r"\s*—\s*Étape\s*", " — ", s, flags=re.I)
    return s

def uid_for(d, title, category):
    key = f"{d}|{normalize_title(title).lower()}|{category.lower()}"
    return "cycling-tv-" + hashlib.sha1(key.encode("utf-8")).hexdigest() + "@lehaire.github.io"

def parse_dt(d, hhmm, tzname):
    h, m = map(int, hhmm.split(":"))
    off = TZ_OFFSETS.get(tzname)
    if off is None:
        off = 2 if tzname == "CEST" else 1 if tzname == "CET" else 0
    # Build a fixed-offset datetime, then convert to Paris.
    from datetime import timezone
    local = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone(timedelta(hours=off)))
    return local.astimezone(PARIS)

def extract_blocks(text):
    # The rendered page has a stable marker immediately before each race title.
    marker = re.compile(r"Copier (?:le nom et les horaires de la course|race name and times|il nome e gli orari della corsa)", re.I)
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]
    starts = [i for i,x in enumerate(lines) if marker.search(x)]
    blocks = []
    for n, i in enumerate(starts):
        j = starts[n+1] if n+1 < len(starts) else len(lines)
        block = lines[i:j]
        if len(block) < 2:
            continue
        # Marker line is followed by the race title.
        title = block[1]
        # Skip accidental headings / UI text.
        if title.lower() in {"copier le nom et les horaires de la course", "copy race name and times"}:
            continue
        blocks.append((title, block))
    return blocks

def find_channel_time(block, channel):
    # Exact channel rows are followed by a time row in Course du Jour.
    for i, line in enumerate(block):
        if channel not in line:
            continue
        # Ignore the compact list of broadcasters at the top of a race block.
        if "(" not in line and not line.endswith("FR"):
            continue
        for nxt in block[i+1:i+4]:
            m = TIME_RE.search(nxt)
            if m:
                return m.group(1), m.group(2), m.group(3)
    return None

def parse_day(d):
    url = BASE.format(d.isoformat())
    r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0 cycling-calendar/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n")
    events = []
    for title, block in extract_blocks(text):
        # Determine discipline/category from nearby text where available.
        category = "Cyclisme"
        joined = " ".join(block[:5])
        if "cyclocross" in joined.lower() or "CX" in joined:
            category = "Cyclocross"
        elif "gravel" in joined.lower():
            category = "Gravel"
        elif "MTB" in joined or "VTT" in joined:
            category = "VTT"
        broadcasters = []
        for ch, label in CHANNELS.items():
            hit = find_channel_time(block, ch)
            if hit:
                start, end, tz = hit
                try:
                    st = parse_dt(d, start, tz)
                    en = parse_dt(d, end or start, tz)
                    if not end:
                        en = st + timedelta(hours=2)
                    broadcasters.append((label, st, en))
                except Exception:
                    pass
        # Group the event by race; use earliest start and latest end if multiple broadcasters.
        if broadcasters:
            st = min(x[1] for x in broadcasters)
            en = max(x[2] for x in broadcasters)
            labels = sorted({x[0] for x in broadcasters})
            events.append({
                "date": d.isoformat(), "start": st, "end": en,
                "title": normalize_title(title), "category": category,
                "broadcasters": labels, "source": url
            })
    return events

def add_manual(events):
    if not MANUAL.exists():
        return events
    for e in json.loads(MANUAL.read_text(encoding="utf-8")):
        st = datetime.fromisoformat(e["date"] + "T" + e["start"]).replace(tzinfo=PARIS)
        en = datetime.fromisoformat(e["date"] + "T" + e["end"]).replace(tzinfo=PARIS)
        e2 = dict(e)
        e2["start_dt"], e2["end_dt"] = st, en
        e2["broadcasters"] = [e["broadcaster"]]
        events.append(e2)
    return events

def merge(events):
    # Stable identity: date + normalized title + category.
    merged = {}
    for e in events:
        key = (e["date"], normalize_title(e["title"]).lower(), e.get("category","Cyclisme").lower())
        if key not in merged:
            merged[key] = dict(e)
            merged[key]["broadcasters"] = sorted(set(e.get("broadcasters", [])))
            merged[key]["start_dt"] = e.get("start_dt", e.get("start"))
            merged[key]["end_dt"] = e.get("end_dt", e.get("end"))
        else:
            m = merged[key]
            m["broadcasters"] = sorted(set(m["broadcasters"]) | set(e.get("broadcasters", [])))
            st = e.get("start_dt", e.get("start"))
            en = e.get("end_dt", e.get("end"))
            m["start_dt"] = min(m["start_dt"], st)
            m["end_dt"] = max(m["end_dt"], en)
            if e.get("source"):
                m["source"] = m.get("source","") + " | " + e["source"]
    return sorted(merged.values(), key=lambda x: x["start_dt"])

def esc(s):
    return str(s).replace("\\","\\\\").replace(";","\\;").replace(",","\\,").replace("\n","\\n")

def ics_dt(dt):
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

def write_ics(events):
    now = datetime.now(ZoneInfo("UTC"))
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Lehaire//Cyclisme TV France//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Cyclisme TV — France",
        "X-WR-TIMEZONE:Europe/Paris",
    ]
    for e in events:
        uid = uid_for(e["date"], e["title"], e.get("category","Cyclisme"))
        labels = " + ".join(e["broadcasters"])
        summary = f"[{labels}] {e['title']}"
        desc = f"Diffusion cyclisme en France\\nDiffuseur(s): {labels}\\nSource: {e.get('source','Course du Jour')}"
        out += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{ics_dt(now)}",
            f"DTSTART:{ics_dt(e['start_dt'])}",
            f"DTEND:{ics_dt(e['end_dt'])}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(desc)}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    OUT.write_text("\r\n".join(out) + "\r\n", encoding="utf-8")

def main():
    today = date.today()
    events = []
    for n in range(DAYS):
        d = today + timedelta(days=n)
        try:
            events.extend(parse_day(d))
            print("OK", d, len(events))
        except Exception as ex:
            print("WARN", d, ex)
    events = add_manual(events)
    events = merge(events)
    write_ics(events)
    print(f"Wrote {len(events)} events to {OUT}")

if __name__ == "__main__":
    main()
