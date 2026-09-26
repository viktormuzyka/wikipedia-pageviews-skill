"""Metrics, confidence rating and ready-to-quote findings for monthly pageview series."""

import math
import statistics

FLAT = 0.05          # |YoY| under 5% counts as "flat"
LOW_VOLUME = 1000    # views/month under which a few readers or bots can swing the trend
SPIKE_FACTOR = 10    # a day with over 10x the median daily views is a spike
LEVELS = {3: "HIGH", 2: "MEDIUM", 1: "LOW"}


# --- Metrics ---------------------------------------------------------------

def monthly(daily: dict[str, int]) -> dict[str, int]:
    """Sum daily views {'YYYY-MM-DD': n} into months {'YYYY-MM': n}."""
    months: dict[str, int] = {}
    for day, views in sorted(daily.items()):
        months[day[:7]] = months.get(day[:7], 0) + views
    return months


def ratio(a: float, b: float) -> float | None:
    """a / b - 1, or None when the base is zero."""
    return a / b - 1 if b else None


def sign_test(wins: int, losses: int) -> float:
    """Two-sided binomial sign test: chance of a split at least this uneven if nothing changed."""
    n, k = wins + losses, max(wins, losses)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n)


def direction(x: float | None) -> int:
    return 0 if x is None or abs(x) < FLAT else (1 if x > 0 else -1)


def metrics(daily: dict[str, int], project: dict[str, int], months: int) -> dict:
    """All numbers for one language: YoY, normalized YoY, consistency, spikes, index series.

    `daily` must cover whole months and at least 24 of them; the last `months` form the window.
    """
    by_month = monthly(daily)
    keys = sorted(by_month)[-months:]
    views = [by_month[k] for k in keys]
    last, prev = views[-12:], views[-24:-12]
    proj_last = sum(project.get(k, 0) for k in keys[-12:])
    proj_prev = sum(project.get(k, 0) for k in keys[-24:-12])

    # Spikes: news, TV shows or bots. Recompute YoY with spike days replaced by the median.
    recent = {d: v for d, v in daily.items() if d[:7] >= keys[-24]}
    median = statistics.median(recent.values())
    spikes = {d: v for d, v in recent.items() if v > SPIKE_FACTOR * max(median, 1)}
    clean = monthly({d: (median if d in spikes else v) for d, v in recent.items()})
    clean_vals = [clean[k] for k in keys[-24:]]

    up = sum(a > b for a, b in zip(last, prev))
    down = sum(a < b for a, b in zip(last, prev))
    base = statistics.mean(views[:12])
    # A leading run of empty months means the article is new or was renamed inside the window.
    first = next((k for k, v in zip(keys, views) if v > 0), None)
    return {
        "months": keys,
        "views": views,
        "project": [project.get(k, 0) for k in keys],
        "index": [round(v / base * 100, 1) for v in views] if base else None,
        "avg_monthly": round(statistics.mean(last)),
        "yoy": ratio(sum(last), sum(prev)),
        "yoy_clean": ratio(sum(clean_vals[-12:]), sum(clean_vals[:12])),
        "norm_yoy": ratio(sum(last) / proj_last, sum(prev) / proj_prev) if proj_last and proj_prev else None,
        "project_yoy": ratio(proj_last, proj_prev),
        "per_million": round(sum(last) / proj_last * 1e6, 1) if proj_last else None,
        "window_change": ratio(sum(last), sum(views[:12])) if months >= 36 else None,
        "months_up": up,
        "months_down": down,
        "sign_p": round(sign_test(up, down), 3),
        "spike_days": sorted(spikes.items(), key=lambda kv: -kv[1])[:3],
        "spike_count": len(spikes),
        "first_month": first if first and first > keys[0] else None,
    }


# --- Confidence ------------------------------------------------------------

def bot_geography(lang: str, countries: list) -> str | None:
    """Reader countries hinting at undetected bots: cloud hubs (US, Singapore) leading a non-English wiki."""
    shares = dict(countries)
    if lang != "en" and (shares.get("US", 0) >= 0.25 or shares.get("SG", 0) >= 0.10):
        return ", ".join(f"{c} {s:.0%}" for c, s in countries)
    return None


def rate(m: dict, proxy: bool = False, bot_geo: str | None = None) -> dict:
    """Add 'trend', 'confidence' (HIGH/MEDIUM/LOW) and 'reasons' to a metrics dict."""
    yoy = m["yoy"]
    trend = {1: "growing", -1: "declining", 0: "flat"}[direction(yoy)]
    agree = m["months_up"] if (yoy or 0) >= 0 else m["months_down"]
    level, reasons = 3, []

    def cap(limit: int, code: str, **params) -> None:
        nonlocal level
        level = min(level, limit)
        reasons.append({"code": code, **params})

    if m["first_month"]:
        cap(1, "new_article", month=m["first_month"])
    if m["avg_monthly"] < LOW_VOLUME:
        cap(1, "low_volume", views=m["avg_monthly"])
    if yoy and m["yoy_clean"] is not None and abs(yoy) >= 0.1 and m["yoy_clean"] / yoy < 0.5:
        cap(2, "spikes", days=m["spike_count"], yoy_clean=m["yoy_clean"])
    if m["norm_yoy"] is not None and direction(yoy) != direction(m["norm_yoy"]):
        cap(2, "wiki_trend", project_yoy=m["project_yoy"], norm_yoy=m["norm_yoy"])
    if trend != "flat" and agree < 10:
        cap(2, "inconsistent", agree=agree)
    if proxy:
        cap(2, "proxy")
    if bot_geo:
        cap(2, "bot_geo", geo=bot_geo)
    if level == 3:
        reasons.append({"code": "stable" if trend == "flat" else "consistent", "agree": agree})
    return {**m, "trend": trend, "agree": agree, "confidence": LEVELS[level], "reasons": reasons}


# --- Ready-to-quote text ---------------------------------------------------

TEXT = {
    "en": {
        "growing": "growing", "declining": "declining", "flat": "roughly flat",
        "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "up": "up", "down": "down",
        "months_up": "{n}/12 months above the same month last year",
        "months_down": "{n}/12 months below the same month last year",
        "ok": "{name}: {trend}, {yoy} year over year and {norm_yoy} relative to the whole {name} "
              "Wikipedia (~{avg} views/month, {months}); confidence {conf}.",
        "window": " Over the whole {years}-year window: {change}.",
        "bot_note": " Its views/month and per-1M numbers look bot-inflated: do not rank it on them.",
        "missing": "{name}: no article on “{topic}” — a content gap, not proof of zero interest.",
        "compare": "Highest interest relative to wiki size: {top_pm} ({pm} views per million {top_pm} "
                   "Wikipedia views); best trend relative to its own wiki: {top_trend} ({norm} vs wiki, {yoy} raw).",
        "window_all": "Change over the whole {years}-year window: {changes}.",
        "not_ranked": "Not ranked, because reader geography suggests bots (numbers marked ?): {names}.",
        "coverage": "Basket coverage differs ({coverage}); compare growth rates, not levels.",
        "by_language": "{name}, most read topic first: {items}.",
        "topic_item": "{topic} ~{avg} views/month ({yoy} YoY, {norm} vs wiki, confidence {conf})",
        "topic_short": "{topic} ~{avg}/mo ({yoy}, {conf})",
        "topic_missing": "{topic}: no article (content gap)",
        "top_all": "Most read topic in every language: {topic}.",
        # Confidence reasons
        "new_article": "article has data only since {month} (new or renamed), so growth is not meaningful",
        "low_volume": "low volume (~{views} views/month): a few readers or bots can swing the numbers",
        "spikes": "the change depends on {days} spike days; without them YoY is {yoy_clean}",
        "wiki_trend": "the whole wiki changed {project_yoy}, so relative to it the topic moved {norm_yoy}",
        "inconsistent": "only {agree}/12 months moved in the trend's direction",
        "proxy": "uses a proxy article that is not the same Wikidata topic",
        "bot_geo": "reader geography ({geo}) is unusual for this language: cloud-hosting hubs (US, Singapore) "
                   "point to undetected bots, so its levels and per-1M numbers are unreliable",
        "consistent": "{agree}/12 months moved in the trend's direction, enough volume, no spike effect",
        "stable": "no clear change year over year, enough volume, no spike effect",
        "group_low_volume": "LOW, volume under 1,000 views/month (a few readers or bots can swing the numbers)",
        "group_consistent": "HIGH, consistent trend with enough volume and no spike effect",
        "group_stable": "HIGH, no clear change with enough volume",
        # Limits
        "lim_pay": "Pageviews show reading interest, not willingness to pay: use them to choose what to validate next.",
        "lim_geo": "A language is not a market: {geo}.",
        "lim_en": "English Wikipedia is read worldwide, so en is not the US or UK market.",
        "lim_basket": "The basket of articles is an assumption: {articles}.",
        "lim_bots": "Only human traffic (agent=user) is counted; some undetected bots may remain.",
    },
    "uk": {
        "growing": "зростає", "declining": "спадає", "flat": "приблизно стабільний",
        "HIGH": "ВИСОКА", "MEDIUM": "СЕРЕДНЯ", "LOW": "НИЗЬКА", "up": "вище", "down": "нижче",
        "months_up": "{n}/12 місяців вище, ніж торік",
        "months_down": "{n}/12 місяців нижче, ніж торік",
        "ok": "{name}: інтерес {trend}, {yoy} рік до року і {norm_yoy} відносно всього розділу "
              "(~{avg} переглядів/міс, {months}); довіра {conf}.",
        "window": " За все {years}-річне вікно: {change}.",
        "bot_note": " Її перегляди/міс і «на 1 млн» схожі на завищені ботами: не ранжуйте за ними.",
        "missing": "{name}: немає статті «{topic}» — це прогалина в контенті, а не доказ нульового інтересу.",
        "compare": "Найвищий інтерес відносно розміру вікі: {top_pm} ({pm} на мільйон переглядів розділу); "
                   "найкращий тренд відносно свого розділу: {top_trend} ({norm} відносно вікі, {yoy} без поправки).",
        "window_all": "Зміна за все {years}-річне вікно: {changes}.",
        "not_ranked": "Не ранжовано, бо географія читачів натякає на ботів (числа з ?): {names}.",
        "coverage": "Покриття кошика різне ({coverage}); порівнюйте темпи зростання, а не рівні.",
        "by_language": "{name}, від найпопулярнішої теми: {items}.",
        "topic_item": "{topic} ~{avg} переглядів/міс ({yoy} рік до року, {norm} відносно вікі, довіра {conf})",
        "topic_short": "{topic} ~{avg}/міс ({yoy}, {conf})",
        "topic_missing": "{topic}: статті немає (прогалина)",
        "top_all": "Найпопулярніша тема в усіх мовах: {topic}.",
        "new_article": "дані є лише з {month} (стаття нова або перейменована), тож зростання не показове",
        "low_volume": "малий обсяг (~{views} переглядів/міс): кілька читачів чи ботів можуть змінити картину",
        "spikes": "зміна залежить від {days} днів-сплесків; без них рік до року {yoy_clean}",
        "wiki_trend": "увесь розділ змінився на {project_yoy}, тож відносно нього тема змінилася на {norm_yoy}",
        "inconsistent": "лише {agree}/12 місяців змінилися в напрямку тренду",
        "proxy": "використано статтю-замінник, що не є тією самою темою у Wikidata",
        "bot_geo": "географія читачів ({geo}) нетипова для цієї мови: хмарні хаби (США, Сінгапур) вказують на "
                   "неідентифікованих ботів, тож рівні й «на 1 млн» ненадійні",
        "consistent": "{agree}/12 місяців у напрямку тренду, достатній обсяг, без впливу сплесків",
        "stable": "без помітної зміни рік до року, достатній обсяг, без впливу сплесків",
        "group_low_volume": "НИЗЬКА, обсяг менше 1 000 переглядів/міс (кілька читачів чи ботів можуть змінити картину)",
        "group_consistent": "ВИСОКА, послідовний тренд, достатній обсяг, без впливу сплесків",
        "group_stable": "ВИСОКА, без помітної зміни, достатній обсяг",
        "lim_pay": "Перегляди показують інтерес до читання, а не готовність платити: це спосіб обрати, що перевіряти далі.",
        "lim_geo": "Мова ≠ ринок: {geo}.",
        "lim_en": "Англійську Wikipedia читають у всьому світі, тож en — не ринок США чи Великої Британії.",
        "lim_basket": "Кошик статей — це припущення: {articles}.",
        "lim_bots": "Враховано лише трафік людей (agent=user); частина ботів може лишатися.",
    },
}


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.0f}%"


def num(x: float | None, lang: str = "en") -> str:
    if x is None:
        return "n/a"
    text = f"{x:,.0f}" if x >= 10 else f"{x:.1f}"
    return text.replace(",", " ") if lang == "uk" else text  # narrow space in Ukrainian


def display_name(r: dict, lang: str = "en") -> str:
    name = r["name_uk"] if lang == "uk" else r["name"]
    return name[:1].upper() + name[1:]  # Ukrainian language names are lowercase


def months_text(r: dict, lang: str = "en", short: bool = False) -> str:
    """Consistency in the trend's direction, e.g. '11/12 months below the same month last year'."""
    down = r["trend"] == "declining"
    n = r["months_down"] if down else r["months_up"]
    if short:
        return f"{n}/12 {TEXT[lang]['down' if down else 'up']}"
    return TEXT[lang]["months_down" if down else "months_up"].format(n=n)


def bot_flagged(r: dict) -> bool:
    return any(x["code"] == "bot_geo" for x in r.get("reasons", []))


def reason_text(reason: dict, lang: str = "en") -> str:
    """Render one confidence reason, e.g. {'code': 'low_volume', 'views': 150}, as a phrase."""
    params = dict(reason)
    for key in ("yoy_clean", "project_yoy", "norm_yoy"):
        if key in params:
            params[key] = pct(params[key])
    if "views" in params:
        params["views"] = num(params["views"], lang)
    return TEXT[lang][reason["code"]].format(**params)


def findings(result: dict, lang: str = "en", per_language: bool = True) -> list[str]:
    """Plain-language sentences built only from computed numbers, for the agent to quote.

    per_language=False keeps only cross-language sentences (the PDF table already has the rest).
    """
    if result.get("compare"):
        return compare_findings(result, lang, short=not per_language)
    t, out = TEXT[lang], []
    for r in result["languages"]:
        name = display_name(r, lang)
        if r["status"] == "not_found":
            out.append(t["missing"].format(name=name, topic=result["topic"]))
            continue
        if not per_language:
            continue
        line = t["ok"].format(name=name, trend=t[r["trend"]], yoy=pct(r["yoy"]), norm_yoy=pct(r["norm_yoy"]),
                              avg=num(r["avg_monthly"], lang), months=months_text(r, lang),
                              conf=t[r["confidence"]])
        if r["window_change"] is not None:
            line += t["window"].format(years=len(r["months"]) // 12, change=pct(r["window_change"]))
        if bot_flagged(r):
            line += t["bot_note"]
        out.append(line)
    found = [r for r in result["languages"] if r["status"] == "ok"]
    # Rank only editions whose traffic looks human, and rank trends relative to each wiki,
    # because editions shrink or grow at different speeds.
    ranked = [r for r in found if not bot_flagged(r)]
    if len(ranked) >= 2:
        top_pm = max(ranked, key=lambda r: r["per_million"] or 0)
        top_trend = max(ranked, key=lambda r: r["norm_yoy"] if r["norm_yoy"] is not None else r["yoy"] or -9)
        out.append(t["compare"].format(top_pm=display_name(top_pm, lang), pm=num(top_pm["per_million"], lang),
                                       top_trend=display_name(top_trend, lang), norm=pct(top_trend["norm_yoy"]),
                                       yoy=pct(top_trend["yoy"])))
    windowed = [r for r in found if r["window_change"] is not None]
    if windowed and not per_language:  # the per-language lines already carry it
        out.append(t["window_all"].format(years=len(windowed[0]["months"]) // 12, changes=", ".join(
            f"{display_name(r, lang)} {pct(r['window_change'])}" for r in windowed)))
    skipped = [display_name(r, lang) for r in found if bot_flagged(r)]
    if len(found) >= 2 and skipped:
        out.append(t["not_ranked"].format(names=", ".join(skipped)))
    coverage = {r["lang"]: r["coverage"] for r in found if r.get("coverage")}
    if len(set(coverage.values())) > 1:
        out.append(t["coverage"].format(coverage=", ".join(f"{k} {v}" for k, v in coverage.items())))
    return out


def compare_findings(result: dict, lang: str = "en", short: bool = False) -> list[str]:
    """One sentence per language ranking the compared topics by views, for the agent to quote."""
    t, out, tops = TEXT[lang], [], {}
    for code in dict.fromkeys(r["lang"] for r in result["languages"]):
        rows = [r for r in result["languages"] if r["lang"] == code]
        found = sorted((r for r in rows if r["status"] == "ok"), key=lambda r: -r["avg_monthly"])
        items = [t["topic_short" if short else "topic_item"].format(topic=r["topic"], avg=num(r["avg_monthly"], lang), yoy=pct(r["yoy"]),
                                        norm=pct(r["norm_yoy"]), conf=t[r["confidence"]]) for r in found]
        items += [t["topic_missing"].format(topic=r["topic"]) for r in rows if r["status"] == "not_found"]
        line = t["by_language"].format(name=display_name(rows[0], lang), items="; ".join(items))
        if any(bot_flagged(r) for r in found):
            line += t["bot_note"]
        out.append(line)
        if found:
            tops[code] = found[0]["topic"]
    if len(tops) > 1 and len(set(tops.values())) == 1:
        out.append(t["top_all"].format(topic=next(iter(tops.values()))))
    return out


def limits(result: dict, lang: str = "en") -> list[str]:
    """Standard caveats that apply to this run, ready to quote."""
    t = TEXT[lang]
    out = [t["lim_pay"]]
    countries = {r["lang"]: r["countries"] for r in result["languages"] if r.get("countries")}
    geo = "; ".join(f"{code}.wikipedia ≈ " + ", ".join(f"{c} {s:.0%}" for c, s in top)
                    for code, top in countries.items())
    if geo:
        out.append(t["lim_geo"].format(geo=geo))
    if "en" in countries or any(r["lang"] == "en" for r in result["languages"]):
        out.append(t["lim_en"])
    if not result.get("compare") and len(result.get("topics", [])) > 1:
        out.append(t["lim_basket"].format(articles="; ".join(x["label"] for x in result["topics"])))
    out.append(t["lim_bots"])
    return out
