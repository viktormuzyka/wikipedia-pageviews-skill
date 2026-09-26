"""Command-line entry point: analyze | find | report. Prints compact text meant for an AI agent."""

import argparse
import datetime as dt
import json
import os
import re
import sys
import traceback
import urllib.error

import analysis
import report
import wiki

WPV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wpv")  # launcher, for NEXT hints
OUTPUT_DIR = os.environ.get("WPV_OUTPUT_DIR", "wpv-output")
HISTORY = 60  # months always fetched, so changing --months later needs no new requests
MAX_LANGS = 8  # the chart palette has 8 distinguishable colors
MAX_TOPICS = 4  # compared topics: one chart panel each
MAX_ROWS = 12  # topics x languages that still fit on one PDF page


# --- Dates -----------------------------------------------------------------

def add_months(day: dt.date, n: int) -> dt.date:
    """First day of the month n months away from `day`."""
    index = day.year * 12 + day.month - 1 + n
    return dt.date(index // 12, index % 12 + 1, 1)


def history(end_month: str | None) -> tuple[dt.date, dt.date]:
    """First and last day of the HISTORY whole months that end with `end_month` (default: last month)."""
    today = dt.date.today()
    last = dt.date.fromisoformat(end_month + "-01") if end_month else add_months(today, -1)
    if last >= today.replace(day=1):
        raise wiki.WikiError(f"--end {end_month} is not a finished month; use {add_months(today, -1):%Y-%m} or earlier.")
    return add_months(last, 1 - HISTORY), add_months(last, 1) - dt.timedelta(days=1)


# --- analyze ---------------------------------------------------------------

def analyze(args) -> None:
    langs = list(dict.fromkeys(wiki.resolve_lang(x) for x in args.langs.split(",") if x.strip()))
    if not 1 <= len(langs) <= MAX_LANGS:
        raise wiki.WikiError(f"use 1-{MAX_LANGS} languages per run (got {len(langs)}); split into several runs.")
    if not 24 <= args.months <= HISTORY:
        raise wiki.WikiError(f"--months must be between 24 and {HISTORY} (YoY needs two full years).")
    overrides: dict[str, list[str]] = {}
    for spec in args.article:
        lang, _, title = spec.partition(":")
        if not title:
            raise wiki.WikiError(f'--article needs "lang:Title", got "{spec}".')
        overrides.setdefault(wiki.resolve_lang(lang), []).append(title.strip())

    if len(args.topic) > MAX_TOPICS or len(args.topic) * len(langs) > MAX_ROWS:
        raise wiki.WikiError(f"compare at most {MAX_TOPICS} topics and {MAX_ROWS} topic-language pairs per run "
                             f"(got {len(args.topic)} x {len(langs)}); split into several runs.")
    start, end = history(args.end)

    # Each --topic is compared separately; "a;b" inside one --topic is a basket summed per language.
    languages, all_topics, names = [], [], []
    for spec in args.topic:
        topics = [wiki.resolve_topic(t, langs, args.topic_lang) for t in spec.split(";") if t.strip()]
        qids = {t["qid"] for t in topics}
        name = " + ".join(t["label"][:1].upper() + t["label"][1:] for t in topics)
        if len(args.topic) == 1 and args.name:
            name = args.name
        for lang in langs:
            entry = analyze_language(lang, topics, qids, overrides.get(lang), start, end, args.months)
            languages.append({**entry, "topic": name})
        all_topics += topics
        names.append(name)
    name = args.name or " vs ".join(names)
    result = {
        "topic": name,
        "compare": len(names) > 1,
        "topics": [{k: t[k] for k in ("qid", "label", "description")} for t in all_topics],
        "window": {"start": f"{add_months(end, 1 - args.months):%Y-%m}", "end": f"{end:%Y-%m}",
                   "months": args.months},
        "generated": dt.date.today().isoformat(),
        "command": "analyze " + " ".join(sys.argv[2:]),
        "languages": languages,
    }
    slug = re.sub(r"\W+", "-", name.lower()).strip("-")[:40]
    # Absolute path: agents often change folders between commands.
    run_dir = os.path.abspath(os.path.join(OUTPUT_DIR, f"{slug}_{'-'.join(langs)}_{args.months}m"))
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    if any(r["status"] == "ok" for r in languages):
        report.chart_png(result, os.path.join(run_dir, "chart.png"))
    print_analysis(result, run_dir)


def analyze_language(lang, topics, qids, manual, start, end, months) -> dict:
    """Find the article(s) for one language, fetch views and compute metrics."""
    base = {"lang": lang, "name": wiki.lang_name(lang), "name_uk": wiki.lang_name(lang, "uk")}
    articles, missing = [], []
    if manual:  # --article overrides the Wikidata links for this language
        for title in manual:
            info = wiki.page(lang, title)
            if not info:
                raise wiki.WikiError(f'no {lang} Wikipedia article "{title}". Try: {WPV} find "{title}" --lang {lang}')
            articles.append({"title": info["title"], "qid": info["qid"], "proxy": info["qid"] not in qids})
    else:
        for topic in topics:
            title = wiki.sitelink(topic, lang)
            if title:
                articles.append({"title": title, "qid": topic["qid"], "proxy": False})
            else:
                missing.append(topic["label"])
    if not articles:
        return {**base, "status": "not_found", "missing": missing}

    daily: dict[str, int] = {}
    for a in articles:
        views = wiki.daily_views(lang, a["title"], start, end)
        a["avg_monthly"] = round(sum(list(analysis.monthly(views).values())[-12:]) / 12)
        for day, n in views.items():
            daily[day] = daily.get(day, 0) + n
    project = wiki.project_monthly(lang, start, end)
    countries = wiki.top_countries(lang, end.year, end.month)
    result = analysis.rate(analysis.metrics(daily, project, months), proxy=any(a["proxy"] for a in articles),
                           bot_geo=analysis.bot_geography(lang, countries))
    return {**base, **result, "status": "ok", "articles": articles, "missing": missing,
            "coverage": None if manual else f"{len(articles)}/{len(topics)}", "countries": countries}


def print_analysis(result: dict, run_dir: str) -> None:
    """Compact, fixed-section summary: everything the agent needs to answer, nothing more."""
    w, out = result["window"], []
    out.append(f"WINDOW {w['start']}..{w['end']} ({w['months']} full months), human views (agent=user), all devices")
    for t in result["topics"]:
        out.append(f"TOPIC {t['label']} = {t['qid']} \"{t['description']}\"")
    out.append(f"{'lang':5} {'language':11} {'article':28} {'views/mo':>9} {'YoY':>6} {'vs wiki':>8} "
               f"{'per 1M':>7} {'months':>11}  confidence")
    group = None
    for r in result["languages"]:
        if result.get("compare") and r["topic"] != group:
            group = r["topic"]
            out.append(f"[{group}]")
        if r["status"] == "not_found":
            out.append(f"{r['lang']:5} {r['name'][:11]:11} NOT FOUND: no article linked to this topic "
                       f"(content gap, not zero interest)")
            continue
        article = r["articles"][0]["title"] if len(r["articles"]) == 1 else f"{len(r['articles'])} articles"
        mark = "?" if analysis.bot_flagged(r) else ""  # volume numbers likely inflated by bots
        out.append(f"{r['lang']:5} {r['name'][:11]:11} {article[:28]:28} {analysis.num(r['avg_monthly']) + mark:>9} "
                   f"{analysis.pct(r['yoy']):>6} {analysis.pct(r['norm_yoy']):>8} "
                   f"{analysis.num(r['per_million']) + mark:>7} {analysis.months_text(r, short=True):>11}  {r['confidence']}")
        if len(r["articles"]) > 1 or r["missing"]:
            parts = [f"{a['title']} {analysis.num(a['avg_monthly'])}/mo" for a in r["articles"]]
            out.append(f"{'':17}· " + "; ".join(parts + [f"missing: {m}" for m in r["missing"]]))
    if any(analysis.bot_flagged(r) for r in result["languages"]):
        out.append("? = likely inflated by undetected bots (see REASONS); never rank or recommend on these numbers")
    out.append("REASONS")
    for r in result["languages"]:
        if r["status"] == "ok":
            label = f"{r['lang']} [{r['topic']}]" if result.get("compare") else r["lang"]
            out.append(f"- {label} {r['confidence']}: " + "; ".join(analysis.reason_text(x) for x in r["reasons"]))
    out.append("FINDINGS (quote these, do not recompute)")
    out += [f"- {line}" for line in analysis.findings(result)]
    out.append("LIMITS (mention these too)")
    out += [f"- {line}" for line in analysis.limits(result)]
    out.append("NEXT")
    for r in result["languages"]:
        if r["status"] == "not_found":
            out.append(f"- {r['lang']}: report the missing article as a content gap. Only if the user wants a proxy: "
                       f"{WPV} find \"{r['topic']}\" --lang {r['lang']}, pick an article about the "
                       f"same concept, re-run with --article \"{r['lang']}:<Title>\" (marked as proxy)")
    out.append(f"- PDF report: write notes.md (## Question, ## Recommendation, ## Next steps), then run: "
               f"{WPV} report --run {run_dir} --notes notes.md --lang en|uk")
    out.append(f"RUN {run_dir} (analysis.json, chart.png)")
    # Small models follow the last instruction they read, so the answer format comes last.
    out.append("ANSWER in the user's language: short answer, FINDINGS numbers, confidence with REASONS, "
               "LIMITS, articles and window used, one next step. If the user asked for a report or PDF, "
               "first create it with the report command above and include the PDF path.")
    print("\n".join(out))


# --- find ------------------------------------------------------------------

def find(args) -> None:
    """Search one language edition and Wikidata, with recent views per candidate article."""
    lang = wiki.resolve_lang(args.lang)
    start, end = history(None)
    out = [f"WIKIPEDIA {lang} search \"{args.text}\" (views/month = last 12 months, humans)"]
    for title in wiki.search(lang, args.text, 6):
        info = wiki.page(lang, title) or {}
        views = analysis.monthly(wiki.daily_views(lang, title, start, end))
        avg = sum(list(views.values())[-12:]) / 12
        note = " (disambiguation page, do not use)" if info.get("disambiguation") else ""
        out.append(f"- {title}  ~{analysis.num(avg)}/month  {info.get('qid') or 'no Wikidata item'}{note}")
    out.append(f"WIKIDATA topics matching \"{args.text}\"")
    out += [f"- {i['qid']} {i['label']}: {i['description']}" for i in wiki.find_items(args.text, lang)]
    out.append(f"NEXT: same topic in all languages: --topic Q123; one language only: --article \"{lang}:Title\"")
    print("\n".join(out))


# --- report ----------------------------------------------------------------

def make_report(args) -> None:
    path = os.path.join(args.run, "analysis.json")
    if not os.path.exists(path):
        raise wiki.WikiError(f"no analysis.json in {args.run}; run analyze first and pass the RUN folder it prints.")
    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    notes = {}
    if args.notes:
        with open(args.notes, encoding="utf-8") as f:
            notes = report.read_notes(f.read())
    report.chart_png(result, os.path.join(args.run, "chart.png"), args.lang)
    report.pdf(result, notes, os.path.join(args.run, "report.pdf"), args.lang)
    with open(os.path.join(args.run, "report.md"), "w", encoding="utf-8") as f:
        f.write(report.markdown(result, notes, args.lang))
    print(f"PDF OK (1 page): {os.path.join(args.run, 'report.pdf')}")
    print(f"MARKDOWN: {os.path.join(args.run, 'report.md')}  CHART: {os.path.join(args.run, 'chart.png')}")
    for key in ("recommendation", "next steps"):
        words = len(notes.get(key, "").split())
        if words > 80:
            print(f"WARNING: '{key}' has {words} words; the PDF shows about 60. Shorten notes.md and re-run.")
        if not words:
            print(f"WARNING: notes.md has no '## {key.capitalize()}' section; the report will lack it.")
    unmatched = report.check_claims(notes.get("recommendation", "") + "\n" + notes.get("next steps", ""), result)
    if unmatched:
        print(f"WARNING: numbers not found in the analysis: {', '.join(unmatched)}. "
              f"Use only numbers printed by analyze, fix notes.md and re-run report.")


# --- main ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="wpv", description="Wikipedia pageview analysis for topic and language decisions.")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("analyze", help="trend, confidence and findings for a topic across languages")
    p.add_argument("--topic", required=True, action="append",
                   help='"English title", "Q123" or "lang:Title"; repeat --topic to compare topics (max 4); '
                        'join titles with ";" to sum them as one basket')
    p.add_argument("--langs", required=True, help="comma-separated Wikipedia codes, e.g. pl,cs")
    p.add_argument("--months", type=int, default=24, help="window length, 24-60 (default 24)")
    p.add_argument("--end", help="last full month YYYY-MM (default: last month)")
    p.add_argument("--article", action="append", default=[], help='"lang:Title" to use instead of Wikidata links')
    p.add_argument("--topic-lang", default="en", help="language of free-text --topic (default en)")
    p.add_argument("--name", help="display name for the topic or basket")
    p.set_defaults(func=analyze)

    p = sub.add_parser("find", help="search articles and Wikidata topics in one language")
    p.add_argument("text")
    p.add_argument("--lang", required=True)
    p.set_defaults(func=find)

    p = sub.add_parser("report", help="one-page PDF + markdown from an analyze run")
    p.add_argument("--run", required=True, help="RUN folder printed by analyze")
    p.add_argument("--notes", help="notes.md with ## Question, ## Recommendation, ## Next steps")
    p.add_argument("--lang", default="en", choices=["en", "uk"], help="report labels language")
    p.set_defaults(func=make_report)

    args = parser.parse_args()
    try:
        args.func(args)
    except wiki.WikiError as e:
        print(f"ERROR: {e}")
        sys.exit(2)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"ERROR: network problem talking to Wikimedia ({e}). Retry in a minute; cached data is reused.")
        sys.exit(3)
    except Exception as e:  # keep stdout short; full traceback goes to a log file
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"ERROR: unexpected {type(e).__name__}: {e} (details in {OUTPUT_DIR}/error.log)")
        sys.exit(1)


if __name__ == "__main__":
    main()
