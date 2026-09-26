"""Access to Wikimedia data: pageviews, Wikidata and MediaWiki APIs, with a small file cache."""

import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = os.environ.get(
    "WPV_USER_AGENT",
    "wikipedia-pageviews-skill/1.0 (+https://github.com/viktormuzyka/wikipedia-pageviews-skill)",
)
CACHE_DIR = os.path.expanduser(os.environ.get("WPV_CACHE_DIR", "~/.cache/wpv/http"))
CACHE_TTL = 24 * 3600  # pageview data for past days never changes; one day keeps metadata fresh
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIDATA = "https://www.wikidata.org/w/api.php"
# Codes people often use for countries instead of languages (no such Wikipedias exist).
COMMON_MISTAKES = {"cz": "cs", "ua": "uk", "jp": "ja", "gr": "el", "dk": "da", "cn": "zh",
                   "rs": "sr", "ir": "fa", "vn": "vi", "il": "he", "by": "be"}


class WikiError(Exception):
    """An input problem the agent can fix (unknown language, bad title, ...)."""


# --- HTTP with cache -------------------------------------------------------

_last_request = 0.0


def get_json(url: str) -> dict | None:
    """GET a JSON URL through the file cache. Returns None for 404."""
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = _fetch(url)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def _fetch(url: str, attempts: int = 4) -> dict | None:
    """Download JSON politely: sequential requests, <5 per second, retries on 429/5xx."""
    global _last_request
    for attempt in range(attempts):
        # Wikimedia's robot policy asks anonymous clients to stay under 5 requests per second.
        time.sleep(max(0.0, _last_request + 0.25 - time.time()))
        _last_request = time.time()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            retry_after = e.headers.get("Retry-After", "")
            time.sleep(int(retry_after) if retry_after.isdigit() else 2 ** attempt)
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def api_url(base: str, **params) -> str:
    """Build a MediaWiki/Wikidata API URL."""
    return base + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})


def wiki_api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


# --- Languages -------------------------------------------------------------

def wikipedias(ui_lang: str = "en") -> dict[str, str]:
    """All open Wikipedias as {code: language name in ui_lang}, e.g. {'pl': 'Polish'}."""
    data = get_json(api_url("https://meta.wikimedia.org/w/api.php", action="sitematrix",
                            smtype="language", smlangprop="code|localname|site",
                            smsiteprop="code|url", smstate="all", uselang=ui_lang))
    result = {}
    for key, entry in data["sitematrix"].items():
        if key == "count":
            continue
        for site in entry.get("site", []):
            if site["code"] == "wiki" and not site.get("closed"):
                # The subdomain is the code the pageviews API expects (e.g. zh-yue, not zh_yue).
                code = site["url"].split("//")[1].split(".")[0]
                result[code] = entry["localname"]
    return result


def resolve_lang(value: str) -> str:
    """Turn 'pl', 'PL', 'Polish' or a common mistake like 'cz' into a Wikipedia language code."""
    v = value.strip().lower()
    sites = wikipedias()
    if v in sites:
        return v
    by_name = {name.lower(): code for code, name in sites.items()}
    if v in by_name:
        return by_name[v]
    if v in COMMON_MISTAKES:
        return COMMON_MISTAKES[v]
    raise WikiError(f'unknown Wikipedia language "{value}". Use codes like pl, cs, uk, de '
                    f"(list: https://meta.wikimedia.org/wiki/List_of_Wikipedias).")


def lang_name(lang: str, ui_lang: str = "en") -> str:
    return wikipedias(ui_lang).get(lang, lang)


# --- Topics and articles ---------------------------------------------------

def find_items(text: str, lang: str = "en", limit: int = 5) -> list[dict]:
    """Search Wikidata items by label/alias in `lang`. Returns [{'qid','label','description'}]."""
    data = get_json(api_url(WIKIDATA, action="wbsearchentities", search=text, language=lang,
                            uselang="en", type="item", limit=limit))
    return [{"qid": s["id"], "label": s.get("label", ""), "description": s.get("description", "")}
            for s in (data or {}).get("search", [])]


def item(qid: str) -> dict:
    """A Wikidata item as {'qid','label','description','sitelinks': {'plwiki': 'Title', ...}}."""
    data = get_json(api_url(WIKIDATA, action="wbgetentities", ids=qid,
                            props="labels|descriptions|sitelinks", languages="en"))
    entity = (data or {}).get("entities", {}).get(qid)
    if not entity or "missing" in entity:
        raise WikiError(f"Wikidata item {qid} does not exist.")
    return {"qid": qid,
            "label": entity.get("labels", {}).get("en", {}).get("value", qid),
            "description": entity.get("descriptions", {}).get("en", {}).get("value", ""),
            "sitelinks": {site: link["title"] for site, link in entity.get("sitelinks", {}).items()}}


def sitelink(topic: dict, lang: str) -> str | None:
    """Title of the topic's article in a language edition, if one exists."""
    # Wikidata site keys use underscores: zh-yue -> zh_yuewiki.
    return topic["sitelinks"].get(lang.replace("-", "_") + "wiki")


def page(lang: str, title: str) -> dict | None:
    """Normalize a title and follow redirects. Returns {'title','qid','disambiguation'} or None."""
    data = get_json(api_url(wiki_api(lang), action="query", titles=title, redirects=1,
                            prop="pageprops", ppprop="wikibase_item|disambiguation"))
    info = data["query"]["pages"][0]
    if info.get("missing") or info.get("invalid"):
        return None
    props = info.get("pageprops", {})
    return {"title": info["title"], "qid": props.get("wikibase_item"),
            "disambiguation": "disambiguation" in props}


def search(lang: str, text: str, limit: int = 5) -> list[str]:
    """Full-text search of article titles in one language edition."""
    data = get_json(api_url(wiki_api(lang), action="query", list="search", srsearch=text,
                            srnamespace=0, srlimit=limit))
    return [hit["title"] for hit in data["query"]["search"]]


def resolve_topic(text: str, langs: list[str], topic_lang: str = "en") -> dict:
    """Find the Wikidata item for a topic given as 'Q123', 'lang:Title' or free text."""
    text = text.strip()
    if re.fullmatch(r"[Qq]\d+", text):
        return item(text.upper())
    match = re.fullmatch(r"([a-z-]{2,12}):(.+)", text)
    if match:
        lang, title = resolve_lang(match[1]), match[2]
        info = page(lang, title)
        if not info or not info["qid"]:
            raise WikiError(f'no {lang} Wikipedia article "{title}" linked to Wikidata. '
                            f'Try: wpv find "{title}" --lang {lang}')
        return item(info["qid"])
    # Free text: an exact article title is the most precise match, e.g. "Neural network (machine learning)".
    info = page(topic_lang, text)
    if info and info["qid"] and not info["disambiguation"]:
        return item(info["qid"])
    # Otherwise search Wikidata in the stated language first, then in the target languages.
    for lang in dict.fromkeys([topic_lang, *langs]):
        # Take the first match that has Wikipedia articles; papers, books and trials usually have none.
        for hit in find_items(text, lang, limit=3):
            topic = item(hit["qid"])
            if any(sitelink(topic, code) for code in ["en", *langs]):
                return topic
    raise WikiError(f'no Wikidata topic matches "{text}". Try the English article title, '
                    f'or: wpv find "{text}" --lang {langs[0]}')


# --- Pageviews -------------------------------------------------------------

def daily_views(lang: str, title: str, start: dt.date, end: dt.date) -> dict[str, int]:
    """Daily views by humans (agent=user) {'YYYY-MM-DD': views}; days the API omits are zeros."""
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")  # "AC/DC" -> "AC%2FDC"
    data = get_json(f"{PAGEVIEWS}/per-article/{lang}.wikipedia/all-access/user/{encoded}"
                    f"/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    views = {(start + dt.timedelta(days=i)).isoformat(): 0 for i in range((end - start).days + 1)}
    for row in (data or {}).get("items", []):
        ts = row["timestamp"]
        views[f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"] = row["views"]
    return views


def project_monthly(lang: str, start: dt.date, end: dt.date) -> dict[str, int]:
    """Monthly human views of a whole language edition {'YYYY-MM': views}, for normalization."""
    data = get_json(f"{PAGEVIEWS}/aggregate/{lang}.wikipedia/all-access/user/monthly"
                    f"/{start:%Y%m%d}00/{end:%Y%m%d}00")
    return {f"{r['timestamp'][:4]}-{r['timestamp'][4:6]}": r["views"]
            for r in (data or {}).get("items", [])}


def top_countries(lang: str, year: int, month: int, n: int = 3) -> list[tuple[str, float]]:
    """Largest reader countries of a language edition as [(country code, approx share)]."""
    data = get_json(f"{PAGEVIEWS}/top-by-country/{lang}.wikipedia/all-access/{year}/{month:02d}")
    if not data:
        return []
    countries = data["items"][0]["countries"]
    # The API publishes rounded-up counts (views_ceil) for privacy, so shares are approximate.
    total = sum(c["views_ceil"] for c in countries)
    return [(c["country"], c["views_ceil"] / total) for c in countries[:n]]
