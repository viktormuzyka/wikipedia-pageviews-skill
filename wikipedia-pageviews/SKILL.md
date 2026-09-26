---
name: wikipedia-pageviews
description: Analyze Wikipedia pageview trends to judge reading interest in a topic across language editions - growth, how far to trust it, charts and a one-page PDF report. Use when the user asks whether interest in a topic is growing, wants to compare languages or audiences (e.g. "Polish vs Czech", "which language to launch next"), is choosing a course or content topic for a B2C product, or wants a shareable report based on Wikipedia pageviews. Not for market size, revenue or search-engine volume.
license: MIT
compatibility: Needs Python 3.11+ and internet access to wikimedia.org and wikidata.org. The first run installs matplotlib into a local virtualenv (about a minute).
metadata:
  version: "1.0"
---

# Wikipedia pageviews for topic and language decisions

Pageviews count how many people (bots excluded) read a Wikipedia article. They are a
proxy for reading interest in a topic, per language edition. **All numbers come from
the `wpv` tool.** Your job: pick the inputs, run the tool, explain its output honestly.

## Tool

`SKILL_DIR` below is the folder that contains this file. Run the tool from the user's working
folder (never `cd` into `SKILL_DIR`); results and your `notes.md` belong in that working folder,
under `./wpv-output/`. The first run prints an install message - just wait.

```bash
SKILL_DIR/scripts/wpv analyze --topic "<topic>" --langs <codes> [options]
SKILL_DIR/scripts/wpv find "<text>" --lang <code>
SKILL_DIR/scripts/wpv report --run <RUN folder> --notes notes.md --lang en|uk
```

`analyze` options:
- `--topic` - English Wikipedia title (`"Intermittent fasting"`), Wikidata id (`Q1666254`)
  or `lang:Title` (`"uk:Астрономія"`).
  - To **compare topics**, repeat it: `--topic "Deep learning" --topic "Computer vision"`
    (max 4 topics, max 12 topic-language pairs). One run, one report.
  - Titles joined by `;` inside one `--topic` are **summed** into one basket per language.
- `--langs` - Wikipedia codes, comma-separated, max 8: `pl,cs,uk,de,es`. (Czech is `cs`,
  Ukrainian `uk`; country codes like `cz`, `ua` are auto-corrected.)
- `--months` - window length, 24 (default) to 60. "Last 3 years" -> `--months 36`.
- `--article "pl:Title"` - use this article for that language instead of the Wikidata link.
- `--name "Learning English"` - display name for a basket.
- `--end 2026-08` - last full month (default: last month).

## Workflow

1. From the request, extract: topic(s), languages, period (default 24 months) and the
   decision the user is making.
2. Map the topic to English Wikipedia article title(s). For a broad intent, build a basket
   of 2-4 articles that reflect it, e.g. learning English ->
   `"English language;English as a second or foreign language;IELTS;TOEFL"`. Tell the user
   which articles you chose - it is an assumption.
3. Run `analyze`. Check the `TOPIC` line: does the description match what the user meant?
   If not, run `find`, then re-run with the right `Q...` id.
   If the user compares several topics, put them all in ONE `analyze` run (repeat `--topic`).
4. `NOT FOUND` for a language = no article on this topic there. Report it as a content gap
   (not zero interest). Use a proxy only if it clearly covers the same concept: run `find`,
   then re-run with `--article "xx:Title"`. Proxies are marked and capped at MEDIUM.
5. Answer with the template below. Quote the `FINDINGS` and `LIMITS` lines; never compute
   new numbers.
6. If the user asks for any report ("short report", PDF, something to share with the team),
   create the PDF as described in "Report" below before you answer.

## Reading the output

- `views/mo` - average monthly human views over the last 12 months.
- `YoY` - last 12 months vs the previous 12. Seasonality (January diets, school year) cancels out.
- `vs wiki` - YoY relative to the whole language edition. Many Wikipedias lose traffic every
  year, so this shows whether the topic did better or worse than its wiki.
- `per 1M` - views per million views of that Wikipedia edition (not per million people):
  interest level comparable across languages.
- `months` - consistency: `11/12 down` = 11 of the last 12 months were below the same month a
  year earlier. 10+ in the trend's direction = consistent.
- `confidence` HIGH / MEDIUM / LOW, with `REASONS`. Always state it and its reasons as printed.
- `FINDINGS` - ready sentences with the key numbers, including which languages are not ranked.
- `LIMITS` - caveats for this run (reader countries, willingness to pay, basket assumption).

## Answer template (reply in the user's language)

1. **Short answer** - 1-2 sentences that answer the question directly.
2. **Numbers** - the `FINDINGS` lines (translate the words, keep every number exact).
3. **How much to trust it** - confidence and its `REASONS`, in plain words.
4. **Assumptions and limits** - the `LIMITS` lines, plus the articles or basket and window used.
5. **Next step** - one concrete suggestion (another language, a longer window, a PDF report).

## Report (PDF)

1. Write `notes.md` in the user's language with exactly these headings:
   ```markdown
   # <short title>
   ## Question
   <the user's question, one sentence>
   ## Recommendation
   <at most 60 words, based on FINDINGS and confidence>
   ## Next steps
   - <2-3 short bullets>
   ```
2. Run `SKILL_DIR/scripts/wpv report --run <RUN folder from analyze> --notes notes.md --lang uk`
   (`uk` for Ukrainian labels, `en` for any other language).
3. If it prints `WARNING`, fix `notes.md` (use only numbers printed by `analyze`) and re-run.
4. Give the user the path to `report.pdf` (and `report.md` for pasting into chat or docs).

## Follow-up questions

Re-run `analyze` with changed flags - data is cached for 24 hours, so this is fast.
"Add Slovak" -> `--langs pl,cs,sk`; "last 3 years" -> `--months 36`; "use X for Polish" ->
`--article "pl:X"`; a new topic -> a new `analyze` run.

## Hard rules

- Use only numbers printed by `wpv`. Never invent, round differently or recompute them.
- Keep the tool's reasons: don't replace them with your own explanations (e.g. don't call a
  bot warning "diaspora").
- Languages listed as "Not ranked" (numbers marked `?`) may look big, but their volume can be
  bot traffic: never recommend them first. Say they need a bot check before any decision.
- A LOW-confidence change is not a trend: say that it is unreliable and why.
- A missing article is a content gap, not proof of zero interest.
- English Wikipedia is read worldwide: never treat `en` as the US or UK market.
- Always name the articles or basket, the window and your assumptions.

## Examples

1. "Compare growth of interest in intermittent fasting in Polish and Czech Wikipedia over the
   last two years." -> `analyze --topic "Intermittent fasting" --langs pl,cs`. Expect a
   missing article in one language and low volume in the other: say so, don't force a ranking.
2. "Is interest in astronomy growing in Ukrainian Wikipedia, and can we trust it?" ->
   `analyze --topic "Astronomy" --langs uk`. Answer with YoY, vs wiki, months, confidence.
3. "Compare interest in learning English across our language editions and prepare a short
   report: which audiences to research next?" ->
   `analyze --topic "English language;English as a second or foreign language;IELTS;TOEFL" --name "Learning English" --langs uk,pl,tr,vi,id`,
   then write `notes.md` and run `report`. Base the ranking on the `FINDINGS` comparison line
   (`per 1M`, `vs wiki`), and mention the confidence of each language.

4. "Compare interest in Computer Vision, Deep Learning and Neural Networks in Ukrainian,
   Polish and Czech Wikipedia" ->
   `analyze --topic "Computer vision" --topic "Deep learning" --topic "Neural network (machine learning)" --langs uk,pl,cs`.
   `FINDINGS` rank the topics in each language; one `report` covers all three.

For how metrics and confidence are computed, how to choose articles or baskets, and known
data problems, read [references/methodology.md](references/methodology.md) - when choosing a
basket or proxy, or when the user asks how the numbers work.
