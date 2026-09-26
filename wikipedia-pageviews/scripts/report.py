"""Chart, one-page PDF and markdown report built from an analysis result."""

import datetime as dt
import re
import textwrap

import matplotlib

matplotlib.use("Agg")  # render to files, no display needed
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

import analysis  # noqa: E402
from analysis import num, pct  # noqa: E402

# Validated colorblind-safe categorical palette, used in this fixed order (never cycled).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
STATUS = {"HIGH": "#0ca30c", "MEDIUM": "#fab219", "LOW": "#ec835a"}  # always shown with a text label
# DejaVu Sans ships with matplotlib and covers Latin, Polish/Czech diacritics and Cyrillic.
plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.edgecolor": AXIS,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK2})

LABELS = {
    "en": {
        "title": "Interest in “{topic}” on Wikipedia", "findings": "Key findings",
        "recommendation": "Recommendation", "next steps": "Next steps",
        "limits": "Confidence and limitations", "question": "Question",
        "chart": "Monthly views by humans, index (first 12 months of the window = 100)",
        "wiki": "whole wiki", "window": "Window {start} – {end} ({months} full months)",
        "cols": ["Language", "Article(s)", "Views/mo", "YoY", "vs wiki", "Per 1M", "Months", "Confidence"],
        "not_found": "no article", "articles": "{n} articles", "topic": "Topic",
        "footer": "Source: Wikimedia Analytics API (pageviews, agent=user), Wikidata. Generated {date} "
                  "by the wikipedia-pageviews skill. vs wiki = YoY relative to the whole language "
                  "edition; Per 1M = views per million views of that edition.",
    },
    "uk": {
        "title": "Інтерес до теми «{topic}» у Wikipedia", "findings": "Головні висновки",
        "recommendation": "Рекомендація", "next steps": "Наступні кроки",
        "limits": "Довіра та обмеження", "question": "Питання",
        "chart": "Перегляди людьми за місяць, індекс (перші 12 місяців вікна = 100)",
        "wiki": "увесь розділ", "window": "Вікно {start} – {end} ({months} повних місяців)",
        "cols": ["Мова", "Стаття(і)", "Перегл./міс", "Рік/рік", "Відн. вікі", "На 1 млн", "Місяці",
                 "Довіра"],
        "not_found": "статті немає", "articles": "{n} статті", "topic": "Тема",
        "footer": "Джерело: Wikimedia Analytics API (перегляди, agent=user), Wikidata. Згенеровано {date} "
                  "навичкою wikipedia-pageviews. Відн. вікі = рік до року відносно всього мовного "
                  "розділу; На 1 млн = переглядів на мільйон переглядів розділу.",
    },
}


# --- Chart -----------------------------------------------------------------

def draw_chart(ax, result: dict, lang: str = "en", title: str | None = None, legend: bool = True) -> None:
    """Indexed monthly lines, one per language, with direct labels for up to 4 series."""
    found = [r for r in result["languages"] if r["status"] == "ok" and r["index"]]
    # Color follows the language, so it stays the same across panels and when a language is missing.
    order = result.get("lang_order") or list(dict.fromkeys(r["lang"] for r in result["languages"]))
    for r in found:
        color = SERIES[order.index(r["lang"])]
        x = [dt.date.fromisoformat(m + "-01") for m in r["months"]]
        name = r["name_uk"] if lang == "uk" else r["name"]
        ax.plot(x, r["index"], color=color, lw=2, solid_capstyle="round", label=f"{r['lang']} · {name}")
        ax.plot(x[-1], r["index"][-1], "o", ms=6, color=color, mec="white", mew=1.5)
        if len(found) <= 4:
            ax.annotate(r["lang"], (x[-1], r["index"][-1]), xytext=(7, 0), textcoords="offset points",
                        va="center", fontsize=8, color=INK2)
    if len(found) == 1 and found[0]["project"][0]:
        # With one language, show the whole edition's trend as the context line.
        r = found[0]
        base = sum(r["project"][:12]) / 12
        x = [dt.date.fromisoformat(m + "-01") for m in r["months"]]
        ax.plot(x, [v / base * 100 for v in r["project"]], color=MUTED, lw=1.2, ls=(0, (4, 3)),
                label=LABELS[lang]["wiki"])
    ax.axhline(100, color=AXIS, lw=0.8, zorder=0)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=8, length=0)
    months = len(found[0]["months"]) if found else 24
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, months // (3 if title else 8))))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set_title(title or LABELS[lang]["chart"], fontsize=9, color=INK2, loc="left")
    if legend:
        ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12),
                  ncol=min(5, len(found) + 1))


def draw_charts(fig, rect: tuple, result: dict, lang: str = "en") -> None:
    """One chart, or small multiples with one panel per topic when topics are compared."""
    x, y, w, h = rect
    if not result.get("compare"):
        draw_chart(fig.add_axes(rect), result, lang)
        return
    topics = list(dict.fromkeys(r["topic"] for r in result["languages"]))
    order = list(dict.fromkeys(r["lang"] for r in result["languages"]))
    gap = 0.03
    width = (w - gap * (len(topics) - 1)) / len(topics)
    axes, legend = [], {}
    for i, topic in enumerate(topics):
        ax = fig.add_axes((x + i * (width + gap), y, width, h), sharey=axes[0] if axes else None)
        part = {**result, "lang_order": order, "languages": [r for r in result["languages"] if r["topic"] == topic]}
        draw_chart(ax, part, lang, title=topic, legend=False)
        for handle, label in zip(*ax.get_legend_handles_labels()):
            legend.setdefault(label, handle)
        axes.append(ax)
    fig.text(x, y + h + 0.03, LABELS[lang]["chart"], fontsize=9, color=INK2)
    fig.legend(list(legend.values()), list(legend), frameon=False, fontsize=8, loc="upper center",
               bbox_to_anchor=(x + w / 2, y - 0.025), ncol=min(5, len(legend)))


def chart_png(result: dict, path: str, lang: str = "en") -> None:
    fig = plt.figure(figsize=(8, 3.6), dpi=150)
    draw_charts(fig, (0.08, 0.22, 0.88, 0.62), result, lang)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# --- Shared report content -------------------------------------------------

def columns(result: dict, lang: str) -> list[str]:
    """Table header; when topics are compared the second column names the topic."""
    cols = list(LABELS[lang]["cols"])
    if result.get("compare"):
        cols[1] = LABELS[lang]["topic"]
    return cols


def table_rows(result: dict, lang: str) -> list[list[str]]:
    """One row per language (per topic and language when comparing), the same numbers the CLI prints."""
    rows = []
    for r in result["languages"]:
        name = f"{r['lang']} {analysis.display_name(r, lang)}"
        if r["status"] == "not_found":
            topic = f"{r['topic']}: " if result.get("compare") else ""
            rows.append([name, topic + LABELS[lang]["not_found"]] + [""] * 6)
            continue
        titles = [a["title"] for a in r["articles"]]
        article = titles[0] if len(titles) == 1 else LABELS[lang]["articles"].format(n=len(titles))
        if result.get("compare"):
            article = r["topic"]
        mark = "?" if analysis.bot_flagged(r) else ""  # volume numbers likely inflated by bots
        rows.append([name, article, num(r["avg_monthly"], lang) + mark, pct(r["yoy"]), pct(r["norm_yoy"]),
                     num(r["per_million"], lang) + mark, analysis.months_text(r, lang, short=True),
                     analysis.TEXT[lang][r["confidence"]]])
    return rows


def limitations(result: dict, lang: str) -> list[str]:
    """Per-language confidence reasons plus the standard caveats."""
    found = [r for r in result["languages"] if r["status"] == "ok"]
    if result.get("compare"):
        return grouped_reasons(found, lang) + analysis.limits(result, lang)
    out = []
    for r in found:
        reasons = "; ".join(analysis.reason_text(x, lang) for x in r["reasons"])
        out.append(f"{r['lang']} {analysis.TEXT[lang][r['confidence']]}: {reasons}.")
    return out + analysis.limits(result, lang)


def grouped_reasons(found: list[dict], lang: str) -> list[str]:
    """With many topic-language pairs, list common reasons once with the pairs they apply to."""
    groups: dict[str, list] = {}
    for r in found:
        for reason in r["reasons"]:
            groups.setdefault(reason["code"], []).append((f"{r['lang']} · {r['topic']}", reason))
    out = []
    for code, items in groups.items():
        if code in ("low_volume", "consistent", "stable"):
            out.append(analysis.TEXT[lang]["group_" + code] + ": " + ", ".join(label for label, _ in items) + ".")
        else:
            out += [f"{label}: {analysis.reason_text(reason, lang)}." for label, reason in items]
    return out


def read_notes(text: str) -> dict:
    """Split notes.md into {'title', 'question', 'recommendation', 'next steps'}."""
    notes, key = {}, None
    for line in text.splitlines():
        if line.startswith("# "):
            notes["title"] = line[2:].strip()
        elif line.startswith("## "):
            key = line[3:].strip().lower()
            notes[key] = ""
        elif key:
            notes[key] += line + "\n"
    return {k: v.strip() for k, v in notes.items()}


def check_claims(text: str, result: dict) -> list[str]:
    """Numbers in the agent's text that match nothing computed (the agent must fix them)."""
    percents, values = set(), set()
    for r in result["languages"]:
        if r["status"] != "ok":
            continue
        for key in ("yoy", "yoy_clean", "norm_yoy", "project_yoy", "window_change"):
            if r.get(key) is not None:
                percents.add(abs(r[key]) * 100)
        values.update([r["avg_monthly"], r["per_million"] or 0, sum(r["views"][-12:]), *r["views"]])
        percents.update(s * 100 for _, s in r.get("countries", []))
    unmatched = []
    for token in re.findall(r"\d[\d,. ]*%?", text):
        token = token.rstrip(".,")
        try:
            value = float(re.sub(r"[, %]", "", token))
        except ValueError:  # e.g. "1..2" is not a number
            continue
        if token.endswith("%"):
            ok = any(abs(value - p) <= 1 for p in percents)
        else:
            # Small counts ("2 years", "10/12") and years are not claims about the data.
            ok = value <= 12 or 1990 <= value <= 2100 or any(abs(value - v) <= 0.02 * v for v in values)
        if not ok:
            unmatched.append(token)
    return unmatched


# --- PDF and markdown ------------------------------------------------------

def pdf(result: dict, notes: dict, path: str, lang: str = "en") -> None:
    """A4 page drawn as one matplotlib figure, so the PDF is always exactly one page."""
    for scale in (1.0, 0.9, 0.8):  # shrink text until everything fits above the footer
        fig, bottom = _page(result, notes, lang, scale)
        if bottom > 0.06 or scale == 0.8:
            break
        plt.close(fig)
    fig.savefig(path)
    plt.close(fig)


def _page(result: dict, notes: dict, lang: str, scale: float):
    L, W, H = LABELS[lang], 8.27, 11.69
    fig = plt.figure(figsize=(W, H))
    y = 0.96

    def write(text: str, size: float = 9, weight: str = "normal", color: str = INK,
              bullet: bool = False, max_lines: int = 6) -> None:
        nonlocal y
        size *= scale
        width = int(880 / size)  # characters per line for DejaVu Sans across the text column
        lines = textwrap.wrap(text, width, initial_indent="• " if bullet else "",
                              subsequent_indent="  " if bullet else "") or [""]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:width - 1] + "…"
        for line in lines:
            fig.text(0.07, y, line, fontsize=size, weight=weight, color=color, va="top")
            y -= size * 1.45 / 72 / H

    def heading(text: str) -> None:
        nonlocal y
        y -= 0.008
        write(text, 10.5, "bold")
        y -= 0.002

    write(notes.get("title") or L["title"].format(topic=result["topic"]), 15, "bold", max_lines=2)
    w = result["window"]
    write(L["window"].format(start=w["start"], end=w["end"], months=w["months"]), 8.5, color=INK2)
    if notes.get("question"):
        write(f"{L['question']}: {notes['question']}", 8.5, color=INK2, max_lines=2)

    heading(L["findings"])
    # With many languages the table carries per-language numbers; keep the cross-language sentences.
    for line in analysis.findings(result, lang, per_language=len(result["languages"]) <= 3):
        write(line, bullet=True, max_lines=3)

    y -= 0.01
    chart_h = 0.21 * scale
    top = 0.02 if result.get("compare") else 0  # small multiples need a shared title line
    draw_charts(fig, (0.08, y - chart_h - top, 0.84, chart_h - 0.02), result, lang)
    y -= chart_h + top + 0.055  # room for the legend under the plot

    # Metrics table as aligned text columns.
    xs = [0.07, 0.19, 0.39, 0.487, 0.555, 0.635, 0.72, 0.83]
    for i, row in enumerate([columns(result, lang)] + table_rows(result, lang)):
        for x, cell in zip(xs, row):
            cell = cell if len(cell) <= 26 else cell[:25] + "…"
            weight, color = ("bold", INK2) if i == 0 else ("normal", INK)
            level = result["languages"][i - 1].get("confidence") if i else None
            if level and x == xs[-1]:
                fig.text(x, y - 0.002, "●", fontsize=8 * scale, color=STATUS[level], va="top")
                x += 0.02
            fig.text(x, y, cell, fontsize=8 * scale, weight=weight, color=color, va="top")
        y -= 0.017 * scale
    y -= 0.004

    for key in ("recommendation", "next steps"):
        if notes.get(key):
            heading(L[key])
            for para in notes[key].splitlines():
                if para.strip():
                    write(para.strip().lstrip("-*• "), bullet=para.lstrip().startswith(("-", "*", "•")),
                          max_lines=4)

    heading(L["limits"])
    for line in limitations(result, lang):
        write(line, 7.5, color=INK2, bullet=True, max_lines=3)

    bottom = y
    footer = L["footer"].format(date=result["generated"])
    for i, line in enumerate(textwrap.wrap(footer, int(880 / 7))):
        fig.text(0.07, 0.035 - i * 0.012, line, fontsize=7, color=MUTED, va="top")
    return fig, bottom


def markdown(result: dict, notes: dict, lang: str = "en") -> str:
    """The same report as markdown, for chat, Slack or Notion."""
    L, w = LABELS[lang], result["window"]
    lines = [f"# {notes.get('title') or L['title'].format(topic=result['topic'])}",
             "", f"_{L['window'].format(start=w['start'], end=w['end'], months=w['months'])}_", ""]
    if notes.get("question"):
        lines += [f"**{L['question']}:** {notes['question']}", ""]
    lines += [f"## {L['findings']}", *[f"- {x}" for x in analysis.findings(result, lang)], "",
              "![chart](chart.png)", "",
              "| " + " | ".join(columns(result, lang)) + " |", "|" + "---|" * len(L["cols"]),
              *["| " + " | ".join(row) + " |" for row in table_rows(result, lang)], ""]
    for key in ("recommendation", "next steps"):
        if notes.get(key):
            lines += [f"## {L[key]}", notes[key], ""]
    lines += [f"## {L['limits']}", *[f"- {x}" for x in limitations(result, lang)], "",
              f"_{L['footer'].format(date=result['generated'])}_"]
    return "\n".join(lines) + "\n"
