#!/usr/bin/env python3
"""petition-feed: a self-updating page of open petitions and action alerts.

Fetches the action listings that animal-welfare and environmental groups keep
current themselves, merges them into one page (newest first, New Jersey items
flagged), and writes a static site for GitHub Pages. Each "Sign" button opens
the group's own form. No curation: an item is listed while its group lists it.

Usage:
  python3 build.py                 # fetch live, update state, render site
  python3 build.py --from-dir DIR  # parse saved <source>.html files instead (testing)

Stdlib only. Exit code 0 when every source parsed at least one item, 2 when some
sources failed (their last good items are kept), 1 when nothing could be built.
A one-line JSON summary is printed to stdout for the runner's heartbeat.
"""
import html
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "items.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
NEW_DAYS = 10          # an item counts as new for this many days after first seen
MIN_ITEMS = 1          # a source returning fewer is treated as failed this run


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(" ".join(s.split()))
    return s.strip()


def strip_tracking(url):
    url = html.unescape(url)
    return re.sub(r"[?&](ms|initialms|initms|ea\.tracking\.id)=[^&#]*", "", url).replace("?&", "?").rstrip("?&")


def ymd(s):
    """20260828 / 2026-08-28 -> '2026-08-28', else None."""
    m = re.fullmatch(r"(20\d\d)(\d\d)(\d\d)", s or "")
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- parsers
# Each returns a list of dicts: url, title, summary, posted (ISO or None), nj (bool).

def parse_aspca(t):
    out = []
    for block in re.findall(r'<article class="[^"]*node-advocacy-alert.*?</article>', t, re.S):
        m = re.search(r'<a href="(https://secure\.aspca\.org/(?:action|take-action)/[^"]+)"', block)
        if not m or "mobile-action-team" in m[1]:
            continue
        href = html.unescape(m[1])
        title = clean((re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S) or [None, ""])[1])
        summary = clean((re.search(r'field-name-field-teaser-blurb.*?<p>(.*?)</p>', block, re.S) or [None, ""])[1])
        dm = re.search(r"-(20\d{6})(?:&|$)", href)
        text = clean(block)
        # result and victory pages ("Did lawmakers pass...", "A hard-fought win") have nothing to sign
        if re.match(r"(Did |A hard-fought win)", summary):
            continue
        # state and city alerts are titled with just the place: lead with it, then the ask
        if summary and PLACE.fullmatch(title) and not re.search(r"\b(Act|Bill)\b", title):
            title, summary = f"{title}: {summary}", ""
        out.append(dict(url=strip_tracking(href), title=title or text[:80], summary=summary,
                        posted=ymd(dm[1]) if dm else None,
                        nj=title.startswith("New Jersey") or "New Jersey" in text))
    return out


PLACE = re.compile(r"[A-Z][a-z]+(?: [A-Z][a-z]+)*(?:, [A-Z][a-z]+(?: [A-Z][a-z]+)*)?")


def parse_humane(t):
    out = []
    for m in re.finditer(r'<a[^>]+href="(https://(?:secure|action)\.humaneworld\.org/page/\d+/[^"]+web_petition[^"]*)"[^>]*>(.*?)</a>(.{0,1500})', t, re.S):
        title = clean(m[2])
        summary = clean((re.search(r"<p>(.*?)</p>", m[3], re.S) or [None, ""])[1])
        if title and not FOREIGN.search(title + " " + summary):
            out.append(dict(url=strip_tracking(m[1]), title=title, summary=summary, posted=None,
                            nj="New Jersey" in title + summary))
    return out


# asks aimed at another country's government or companies (the reader is in New Jersey)
FOREIGN = re.compile(r"\b(Canad\w*|U\.?K\.?|United Kingdom|British|Britain|England|Scotland|Wales|"
                     r"Ireland|Austral\w*|India|Indian government|Mexic\w*|Brazil\w*|Europe\w*|EU|"
                     r"South Korea\w*|Korea\w*|China|Chinese|Japan\w*|Viet\w*|Indonesia\w*|Philippin\w*|"
                     r"South Africa\w*|Kenya\w*|Peru\w*|Chile\w*|Ecuador\w*|Costa Rica\w*)\b")


def parse_aldf(t):
    out, seen = [], set()
    for m in re.finditer(r'<h3 class="pt-cv-title"[^>]*><a href="(https://aldf\.org/article/[^"]+)"[^>]*>(.*?)</a></h3>(.{0,1200})', t, re.S):
        if m[1] in seen:
            continue
        seen.add(m[1])
        title = clean(m[2])
        summary = clean((re.search(r'pt-cv-ctf-value">(.*?)</div>', m[3], re.S) or [None, ""])[1])
        out.append(dict(url=m[1], title=title, summary=summary, posted=None,
                        nj=title.startswith("New Jersey") or "New Jersey" in summary))
    return out


EARTH_SKIP = ("guide", "join", "receive-breaking-news")


def parse_earthjustice(t):
    out, seen = [], set()
    for m in re.finditer(r'(.{0,600})<h3[^>]*><a href="(https://earthjustice\.org/action/[^"?]+)[^"]*">(.*?)</a></h3>(.{0,600})', t, re.S):
        url = m[2]
        if url in seen or any(s in url for s in EARTH_SKIP):
            continue
        seen.add(url)
        left = re.search(r"(\d+) Days? Remain", m[1])
        summary = clean((re.search(r"<p[^>]*>(?!<a)(.*?)</p>", m[4], re.S) or [None, ""])[1])
        if summary.lower() in ("take action", ""):
            summary = ""
        title = clean(m[3])
        out.append(dict(url=url, title=title, summary=summary, posted=None,
                        nj="New Jersey" in title + summary,
                        note=f"{left[1]} days left" if left else None))
    return out


NRDC_CARD = re.compile(
    r'<a class="c-card__link" href="(https://action\.nrdc\.org/(?:petition|letter)/[^"]+)">'
    r'<h3 class="c-card__title">(.*?)</h3></a>(.{0,1500})'
    r'|<a class="c-teaser__title-link" href="(https://action\.nrdc\.org/(?:petition|letter)/[^"]+)">'
    r'(.*?)</a>(.{0,1500})', re.S)


def parse_nrdc(t):
    out, seen = [], set()
    for m in NRDC_CARD.finditer(t):
        href, title, rest = (m[1], m[2], m[3]) if m[1] else (m[4], m[5], m[6])
        href = html.unescape(href)
        base = strip_tracking(href)
        if base in seen or "email-and-text-alerts" in base:
            continue
        seen.add(base)
        summary = clean((re.search(r'c-(?:card|teaser)__summary">(.*?)</div>', rest, re.S) or [None, ""])[1])
        where = clean((re.findall(r'c-(?:card|teaser)__detail">(.*?)</span>', rest) or [""])[-1])
        title = clean(title)
        if where and "United States" not in where:
            continue
        dm = re.search(r"-(\d\d)(\d\d)(\d\d)(?:\?|$)", base)
        posted = ymd(f"20{dm[3]}{dm[1]}{dm[2]}") if dm else None
        out.append(dict(url=base, title=title, summary=summary, posted=posted,
                        nj="New Jersey" in summary + where))
    return out


SOURCES = [
    dict(key="aspca", name="ASPCA", cause="Animals",
         url="https://www.aspca.org/get-involved/advocacy-center", parse=parse_aspca),
    dict(key="humane", name="Humane World for Animals", cause="Animals",
         url="https://www.humaneworld.org/en/take-action/action-alerts", parse=parse_humane),
    dict(key="aldf", name="Animal Legal Defense Fund", cause="Animals",
         url="https://aldf.org/take-action/", parse=parse_aldf),
    dict(key="earth", name="Earthjustice", cause="Environment",
         url="https://earthjustice.org/action/alerts", parse=parse_earthjustice),
    dict(key="nrdc", name="NRDC", cause="Environment",
         url="https://www.nrdc.org/actions", parse=parse_nrdc),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- render

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Petitions</title>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Petitions">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#1f6f5c">
<meta name="robots" content="noindex">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d1d1b;--muted:#6b6a65;--line:#e4e2dc;--accent:#1f6f5c;--new:#c2410c;--nj:#1d4ed8;--chip:#ecebe6}
@media (prefers-color-scheme:dark){:root{--bg:#121211;--card:#1c1c1a;--ink:#f1f0ec;--muted:#a3a29c;--line:#2e2e2b;--accent:#5fbfa5;--new:#fb923c;--nj:#93b4ff;--chip:#2a2a27}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
header{padding:calc(env(safe-area-inset-top) + 18px) 16px 6px;max-width:680px;margin:0 auto}
h1{font-size:28px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:14px;margin:0}
nav{position:sticky;top:0;z-index:2;background:var(--bg);padding:10px 16px;max-width:680px;margin:0 auto;display:flex;gap:8px;overflow-x:auto}
nav button{border:0;background:var(--chip);color:var(--ink);padding:8px 14px;border-radius:999px;font:inherit;font-size:15px;white-space:nowrap}
nav button[aria-pressed=true]{background:var(--accent);color:#fff}
main{max-width:680px;margin:0 auto;padding:4px 16px calc(env(safe-area-inset-bottom) + 32px)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 14px 12px;margin:10px 0}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12.5px;color:var(--muted);margin-bottom:6px}
.tag{font-weight:600;font-size:11.5px;letter-spacing:.03em;text-transform:uppercase;border-radius:6px;padding:2px 6px}
.t-new{color:var(--new);border:1px solid var(--new)}
.t-nj{color:var(--nj);border:1px solid var(--nj)}
.card h2{font-size:17px;margin:0 0 4px;line-height:1.3}
.card p{margin:0 0 10px;color:var(--muted);font-size:14.5px}
.sign{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font-weight:600;padding:9px 16px;border-radius:10px;font-size:15px}
.empty{color:var(--muted);text-align:center;padding:30px 0}
footer{color:var(--muted);font-size:12.5px;text-align:center;padding:8px 16px 24px}
footer a{color:inherit}
</style>
</head>
<body>
<header>
<h1>Petitions</h1>
<p class="sub">Animals &amp; environment &middot; updated __UPDATED__</p>
</header>
<nav aria-label="Filter">
<button data-f="all" aria-pressed="true">All</button>
<button data-f="new" aria-pressed="false">New</button>
<button data-f="Animals" aria-pressed="false">Animals</button>
<button data-f="Environment" aria-pressed="false">Environment</button>
<button data-f="nj" aria-pressed="false">New Jersey</button>
</nav>
<main id="list">
__CARDS__
<p class="empty" id="empty" hidden>Nothing here right now.</p>
</main>
<footer>Each petition opens on the group's own site. Listed from: __SOURCES__.</footer>
<script>
(function(){
  var btns=[].slice.call(document.querySelectorAll('nav button'));
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var empty=document.getElementById('empty');
  function apply(f){
    var shown=0;
    cards.forEach(function(c){
      var ok=f==='all'||(f==='new'&&c.dataset.new==='1')||(f==='nj'&&c.dataset.nj==='1')||c.dataset.cause===f;
      c.hidden=!ok; if(ok)shown++;
    });
    empty.hidden=shown>0;
    btns.forEach(function(b){b.setAttribute('aria-pressed',b.dataset.f===f?'true':'false')});
    try{localStorage.setItem('pf-filter',f)}catch(e){}
  }
  btns.forEach(function(b){b.addEventListener('click',function(){apply(b.dataset.f)})});
  var f='all'; try{f=localStorage.getItem('pf-filter')||'all'}catch(e){}
  apply(f);
})();
</script>
</body>
</html>
"""


def card(it):
    tags = []
    if it["is_new"]:
        tags.append('<span class="tag t-new">New</span>')
    if it.get("nj"):
        tags.append('<span class="tag t-nj">NJ</span>')
    meta = [f"{html.escape(it['source'])}", html.escape(it["cause"])]
    if it.get("note"):
        meta.append(html.escape(it["note"]))
    summary = f"<p>{html.escape(it['summary'][:260])}</p>" if it.get("summary") else ""
    return (f'<article class="card" data-cause="{it["cause"]}" data-new="{1 if it["is_new"] else 0}" '
            f'data-nj="{1 if it.get("nj") else 0}">'
            f'<div class="meta">{"".join(tags)}<span>{" &middot; ".join(meta)}</span></div>'
            f'<h2>{html.escape(it["title"])}</h2>{summary}'
            f'<a class="sign" href="{html.escape(it["url"])}" target="_blank" rel="noopener">Sign</a></article>')


def order(items):
    """New items first (newest first), then New Jersey, then items with a closing
    deadline (soonest first), then everything else interleaved across groups so one
    large listing does not bury the others."""
    def days_left(v):
        m = re.match(r"(\d+) days left", v.get("note") or "")
        return int(m[1]) if m else None

    def recency(v):
        fs = v["first_seen"] if v["first_seen"] != "baseline" else ""
        return (fs, v.get("posted") or "")

    new = sorted((v for v in items if v["is_new"]), key=recency, reverse=True)
    rest = [v for v in items if not v["is_new"]]
    nj = [v for v in rest if v.get("nj")]
    rest = [v for v in rest if not v.get("nj")]
    dated = sorted((v for v in rest if days_left(v) is not None), key=days_left)
    rest = [v for v in rest if days_left(v) is None]
    queues = {}
    for v in sorted(rest, key=recency, reverse=True):
        queues.setdefault(v["source_key"], []).append(v)
    mixed = []
    while any(queues.values()):
        for k in [s["key"] for s in SOURCES]:
            if queues.get(k):
                mixed.append(queues[k].pop(0))
    return new + nj + dated + mixed


def main(argv):
    from_dir = None
    if "--from-dir" in argv:
        from_dir = Path(argv[argv.index("--from-dir") + 1])
    today = datetime.now(timezone.utc).astimezone().date()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"items": {}, "sources": {}}
    first_run = not state["items"]
    live, report = {}, {}
    for s in SOURCES:
        try:
            text = (from_dir / f"{s['key']}.html").read_text(errors="replace") if from_dir else fetch(s["url"])
            items = s["parse"](text)
        except Exception as e:  # network or parse failure: keep last good items
            items, err = [], f"{type(e).__name__}"
        else:
            err = None if len(items) >= MIN_ITEMS else "no-items"
        report[s["key"]] = len(items) if not err else err
        if err:
            kept = [k for k, v in state["items"].items() if v["source_key"] == s["key"] and v.get("listed")]
            for k in kept:
                live[k] = state["items"][k]
            continue
        for it in items:
            k = it["url"]
            prev = state["items"].get(k, {})
            first_seen = prev.get("first_seen") or ("baseline" if first_run else today.isoformat())
            live[k] = dict(it, source=s["name"], source_key=s["key"], cause=s["cause"],
                           first_seen=first_seen, listed=True)
    # items no longer listed by their group drop off the page; keep a short memory so a
    # re-listed item is not shown as new again
    for k, v in state["items"].items():
        if k not in live:
            v["listed"] = False
    state["items"].update(live)
    state["sources"] = report
    state["updated"] = today.isoformat()

    def is_new(v):
        fs = v["first_seen"]
        if fs != "baseline":
            return (today - date.fromisoformat(fs)).days < NEW_DAYS
        return bool(v.get("posted")) and (today - date.fromisoformat(v["posted"])).days < NEW_DAYS

    shown = [v for v in state["items"].values() if v.get("listed")]
    for v in shown:
        v["is_new"] = is_new(v)

    shown = order(shown)

    if not shown:
        print(json.dumps({"ok": False, "sources": report, "shown": 0}))
        return 1
    page = (PAGE.replace("__UPDATED__", today.strftime("%b %-d"))
                .replace("__SOURCES__", ", ".join(html.escape(s["name"]) for s in SOURCES))
                .replace("__CARDS__", "\n".join(card(v) for v in shown)))
    (ROOT / "index.html").write_text(page)
    for v in state["items"].values():
        v.pop("is_new", None)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    failed = [k for k, v in report.items() if not isinstance(v, int)]
    print(json.dumps({"ok": not failed, "sources": report, "shown": len(shown),
                      "new": sum(1 for v in shown if is_new(v)), "nj": sum(1 for v in shown if v.get("nj"))}))
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
