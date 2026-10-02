#!/usr/bin/env python3
import hashlib, html, json, re, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

BASE = "https://coursedujour.com/fr/day/{}/"
DAYS = 60
OUT = Path("calendar.ics")
MANUAL = Path("manual_events.json")
PARIS = ZoneInfo("Europe/Paris")
CHANNEL_PAGES = {\n    "EUROSPORT": "https://coursedujour.com/fr/chaines/eurosport/",\n    "FRANCE TV": "https://coursedujour.com/fr/chaines/france-tv/",\n}\n
# Diffuseurs français que nous voulons suivre.\n# Source principale: Course du Jour, avec dédoublonnage par course/date/discipline.
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
    "Novo19": "NOVO19",
}

TZ_OFFSETS = {
    "CET": 1, "CEST": 2, "UTC": 0, "GMT": 0,
    "GMT+1": 1, "GMT+2": 2, "GMT+3": 3, "GMT+4": 4,
    "GMT+5": 5, "GMT+6": 6, "GMT+7": 7, "GMT+8": 8, "GMT+9": 9,
    "EDT": -4, "EST": -5, "PDT": -7, "PST": -8,
    "EET": 2, "EEST": 3, "JST": 9,
}

TIME_RE = re.compile(
    r"\b(\d{1,2}:\d{2})(?:\s*[–-]\s*(\d{1,2}:\d{2}))?\s*"
    r"([A-Z]{2,5}(?:[+-]\d+)?)\b"
)

DISCIPLINE_HEADINGS = {
    "route": "Route",
    "cx": "Cyclocross",
    "cyclocross": "Cyclocross",
    "gravel": "Gravel",
    "mtb": "VTT",
    "vtt": "VTT",
}

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
    off = TZ_OFFSETS.get(tzname, 2 if tzname == "CEST" else 1 if tzname == "CET" else 0)
    local = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone(timedelta(hours=off)))
    return local.astimezone(PARIS)

def fetch_day(d):
    url = BASE.format(d.isoformat())
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LehaireCyclingCalendar/1.1)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
        "Referer": "https://coursedujour.com/fr/",
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30, headers=headers)
            if r.status_code == 200:
                return r.text, url
            # Future pages often do not exist yet. Do not waste retries on 404.
            if r.status_code == 404:
                raise RuntimeError("HTTP 404")
            last = f"HTTP {r.status_code}"
        except Exception as ex:
            last = repr(ex)
            if "HTTP 404" in last:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "request failed")

def extract_blocks(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    marker = re.compile(
        r"Copier .*?(?:nom et les horaires|horaire|horaires).*?(?:course|race)",
        re.I
    )
    starts = [i for i, x in enumerate(lines) if marker.search(x)]

    blocks = []
    current_section = "Cyclisme"
    for n, i in enumerate(starts):
        # Recover the nearest discipline heading before the race.
        for prev in range(i - 1, max(-1, i - 15), -1):
            low = lines[prev].lower()
            if low in DISCIPLINE_HEADINGS:
                current_section = DISCIPLINE_HEADINGS[low]
                break

        j = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[i:j]
        if len(block) < 2:
            continue
        title = block[1]
        if title.lower() in {
            "copier le nom et les horaires de la course",
            "copy race name and times",
        }:
            continue
        blocks.append((title, block, current_section))
    return blocks

def find_channel_time(block, channel):
    for i, line in enumerate(block):
        if channel not in line:
            continue
        # Ignore the compact broadcaster list above the detailed rows.
        if "(" not in line and not line.endswith("FR"):
            continue
        for nxt in block[i + 1:i + 5]:
            m = TIME_RE.search(nxt)
            if m:
                return m.group(1), m.group(2), m.group(3)
    return None

def parse_day(d):
    text, url = fetch_day(d)
    if d == datetime.now(PARIS).date():
        ids = [s.get("id") for s in BeautifulSoup(text, "html.parser").find_all("script", {"type":"application/json"})]
        print("DEBUG JSON script ids:", ids)
        occ = [m.start() for m in re.finditer(re.escape("Eurosport / HBO Max"), text)]
        print("DEBUG Eurosport occurrences:", len(occ), "last:", occ[-1] if occ else -1)
        if occ:
            raw_idx = occ[-1]
            print("DEBUG last Eurosport snippet:", repr(text[max(0, raw_idx-800):raw_idx+2500]))
        for needle in ["L'EquipeTV", "France 3", "broadcast", "/api/", "__NEXT_DATA__"]:
            print("DEBUG", needle, text.lower().count(needle.lower()))
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text("\n")
    if d == datetime.now(PARIS).date():
        marker_probe = re.compile(r"Copier .*?(?:nom et les horaires|horaire|horaires).*?(?:course|race)", re.I)
        print("DEBUG raw Copier:", "Copier" in text, "marker:", len(marker_probe.findall(text)), "chars:", len(text))
        idx = text.find("Copier")
        if idx >= 0:
            print("DEBUG snippet:", repr(text[max(0, idx-250):idx+350]))
    events = []

    blocks = extract_blocks(text)
    if d == datetime.now(PARIS).date():
        print("DEBUG blocks:", [(b[0], len(b[1]), b[1][:8]) for b in blocks])
    for title, block, category in blocks:
        broadcasters = []
        if d == datetime.now(PARIS).date():
            print("DEBUG channel hits:", {ch: find_channel_time(block, ch) for ch in CHANNELS if any(ch in x for x in block)})
        for ch, label in CHANNELS.items():
            hit = find_channel_time(block, ch)
            if not hit:
                continue
            start, end, tz = hit
            try:
                st = parse_dt(d, start, tz)
                en = parse_dt(d, end or start, tz)
                if not end:
                    en = st + timedelta(hours=2)
                broadcasters.append((label, st, en))
            except Exception:
                pass

        if broadcasters:
            st = min(x[1] for x in broadcasters)
            en = max(x[2] for x in broadcasters)
            labels = sorted({x[0] for x in broadcasters})
            events.append({
                "date": d.isoformat(),
                "start": st,
                "end": en,
                "title": normalize_title(title),
                "category": category,
                "broadcasters": labels,
                "source": url,
            })
    return events


MONTHS = {
    "jan":1,"janv":1,"janvier":1,"fév":2,"fev":2,"févr":2,"fevr":2,"février":2,"fevrier":2,
    "mar":3,"mars":3,"avr":4,"avril":4,"mai":5,"juin":6,"juil":7,"juillet":7,
    "aoû":8,"aou":8,"août":8,"aout":8,"sep":9,"sept":9,"septembre":9,
    "oct":10,"octobre":10,"nov":11,"novembre":11,"déc":12,"dec":12,"décembre":12,"decembre":12
}
BROADCAST_RE = re.compile(
    r"^(?P<title>.+?)\s+on\s+(?P<channel>Eurosport / HBO Max|Eurosport / Discovery\+|L'EquipeTV|France TV|France 2|France 3|France 4|france\.tv|Novo19)"
    r"(?:\s+\([^)]+\))?\s+·\s+(?P<date>\d{1,2}\s+[A-Za-zÀ-ÿ.]+\s+\d{4})\s+·\s+(?P<times>[^·]+?)\s+·",
    re.I,
)
def parse_date_fragment(s):
    m=re.search(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)(?:\s+(\d{4}))?",clean(s).replace(".",""))
    if not m: return None
    mon=MONTHS.get(m.group(2).lower())
    return datetime(int(m.group(3) or 2026),mon,int(m.group(1))).date() if mon else None

def parse_channel_page(url,label):
    soup=BeautifulSoup(requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=30).text,"html.parser")
    events=[]; title=None
    for n in soup.find_all(["h2","h3","li"]):
        if n.name=="h2": title=None; continue
        if n.name=="h3":
            t=clean(n.get_text(" ",strip=True))
            if t and t.lower() not in {"courses en vedette","derniers résumés"}: title=t
            continue
        if not title: continue
        txt=clean(n.get_text(" ",strip=True))
        if "Copier" not in txt: continue
        tm=TIME_RE.search(txt)
        if not tm: continue
        if label=="EUROSPORT" and "(" in txt:
            reg=re.search(r"\(([^)]+)\)",txt)
            if reg and "FR" not in reg.group(1).upper(): continue
        dm=re.search(r"(?:lun|mar|mer|jeu|ven|sam|dim)\.?\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)",txt,re.I)
        if not dm: continue
        d=parse_date_fragment(dm.group(0))
        if not d: continue
        st=parse_dt(d,tm.group(1),tm.group(3)); en=parse_dt(d,tm.group(2) or tm.group(1),tm.group(3))
        if not tm.group(2): en=st+timedelta(hours=2)
        events.append({"date":d.isoformat(),"start_dt":st,"end_dt":en,"title":normalize_title(title),"category":infer_category(title),"broadcasters":[label],"source":url})
    return events

def parse_day_broadcasts(d):
    url=BASE.format(d.isoformat())
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=30)
    if r.status_code!=200: raise RuntimeError(f"HTTP {r.status_code}")
    soup=BeautifulSoup(r.text,"html.parser")
    races=[clean(h.get_text(" ",strip=True)) for h in soup.find_all(["h3","h4"])]
    events=[]
    for p in soup.find_all("p"):
        m=BROADCAST_RE.search(clean(p.get_text(" ",strip=True)))
        if not m: continue
        bd=parse_date_fragment(m.group("date"))
        if bd!=d: continue
        tm=TIME_RE.search(m.group("times"))
        if not tm: continue
        label=next((v for k,v in CHANNELS.items() if k.lower()==m.group("channel").lower()),None)
        if not label: continue
        title=m.group("title")
        # Restore the full race title by token overlap.
        toks={x for x in re.findall(r"[\wÀ-ÿ]+",title.lower()) if len(x)>2 and x not in {"euros","race","road"}}
        best=title; score=0
        for rt in races:
            s=len(toks & {x for x in re.findall(r"[\wÀ-ÿ]+",rt.lower()) if len(x)>2})
            if s>score: best,score=rt,s
        if score>=2: title=best
        st=parse_dt(d,tm.group(1),tm.group(3)); en=parse_dt(d,tm.group(2) or tm.group(1),tm.group(3))
        if not tm.group(2): en=st+timedelta(hours=2)
        events.append({"date":d.isoformat(),"start_dt":st,"end_dt":en,"title":normalize_title(title),"category":infer_category(title),"broadcasters":[label],"source":url})
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
    # Stable identity: date + normalized title + discipline.
    merged = {}
    for e in events:
        key = (
            e["date"],
            normalize_title(e["title"]).lower(),
            e.get("category", "Cyclisme").lower(),
        )
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
                old = m.get("source", "")
                if e["source"] not in old.split(" | "):
                    m["source"] = (old + " | " + e["source"]).strip(" |")
    return sorted(merged.values(), key=lambda x: x["start_dt"])

def esc(s):
    return (
        str(s).replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )

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
        uid = uid_for(e["date"], e["title"], e.get("category", "Cyclisme"))
        labels = " + ".join(e["broadcasters"])
        summary = f"[{labels}] {e['title']}"
        desc = (
            f"Diffusion cyclisme en France\\n"
            f"Diffuseur(s): {labels}\\n"
            f"Discipline: {e.get('category','Cyclisme')}\\n"
            f"Source: {e.get('source','Course du Jour')}"
        )
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
    events = []
    for label, url in CHANNEL_PAGES.items():
        try:
            got = parse_channel_page(url, label)
            events.extend(got)
            print("CHANNEL", label, len(got))
        except Exception as ex:
            print("WARN CHANNEL", label, ex)
    today = datetime.now(PARIS).date()
    for n in range(10):
        d = today + timedelta(days=n)
        try:
            got = parse_day_broadcasts(d)
            events.extend(got)
            print("DAY", d, len(got))
        except Exception as ex:
            print("WARN DAY", d, ex)
    events = add_manual(events)
    events = merge(events)
    write_ics(events)
    print(f"Wrote {len(events)} unique events to {OUT}")

if __name__ == "__main__":
    main()
