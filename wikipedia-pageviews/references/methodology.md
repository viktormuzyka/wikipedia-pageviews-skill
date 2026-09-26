# Methodology

How `wpv` turns pageviews into findings, and what the data can and cannot say.

## Data

- **Source**: Wikimedia Analytics API, per-article daily pageviews with `agent=user`
  (known bots and crawlers excluded) and `access=all-access` (desktop, mobile web, apps).
- **History**: the tool always fetches 60 whole months ending with the last finished month,
  so changing `--months` needs no new requests. Days with zero views (omitted by the API)
  are filled with zeros. The current, unfinished month is never used.
- **Topic -> articles**: the topic is matched to a Wikidata item; its sitelinks give the
  article title in each language. This compares the *same concept* across languages.
- **Normalization**: monthly views of the whole language edition (same agent and access).
- **Reader geography**: the edition's top countries for the last month (`top-by-country`).
- **Cache**: every HTTP response is stored in `~/.cache/wpv/http` for 24 hours.

## Metrics

| Metric | Definition | Why |
|---|---|---|
| `views/mo` | mean monthly views, last 12 months | volume, i.e. how much signal there is |
| `YoY` | sum of the last 12 months / sum of the previous 12 - 1 | same months compared, so seasonality cancels out |
| `vs wiki` | the article's share of edition views, last 12 months vs previous 12, - 1 | removes the edition-wide trend (AI answers, bot reclassification, reader migration) |
| `per 1M` | views per million edition views, last 12 months | interest level comparable across languages of different size |
| `months` | months of the last 12 above (`up`) or, for a decline, below (`down`) the same month a year earlier | consistency; a two-sided sign test p-value is stored in `analysis.json` |
| window change | last 12 months vs the first 12 of the window (only with `--months` >= 36) | longer-run change |

Trend label: YoY above +5% = growing, below -5% = declining, otherwise roughly flat.

## Confidence rules

The tool starts at HIGH and applies caps. Each cap adds a reason.

| Check | Rule | Cap |
|---|---|---|
| New or renamed article | leading empty months inside the window | LOW |
| Low volume | fewer than 1,000 views per month | LOW |
| Spike-driven | a spike day has over 10x the median daily views; if YoY recomputed without spike days keeps less than half of the change (or flips its sign), the change is spike-driven | MEDIUM |
| Wiki trend disagrees | raw YoY and `vs wiki` point in different directions (growing / flat / declining) | MEDIUM |
| Inconsistent | fewer than 10 of 12 months moved in the trend's direction | MEDIUM |
| Proxy article | an `--article` whose Wikidata item differs from the topic | MEDIUM |
| Bot geography | on a non-English edition, the US has 25% or more of readers, or Singapore 10% or more. Both are cloud hubs, so this points to undetected bots | MEDIUM |

HIGH therefore means: enough volume, a consistent direction in at least 10 of 12 months,
not spike-driven, and the same direction relative to the wiki.

## Choosing articles

- **One concept**: use the English title of the article (`"Astronomy"`). Check the `TOPIC`
  description in the output: `"Mercury"` could be a planet or an element.
- **An intent, not a concept** (learning English, home workouts): build a basket of 2-4
  articles that people who have this intent read. For example, exam and method articles
  (`IELTS`, `TOEFL`) plus the core subject (`English language`). A core article like
  `English language` also attracts readers with other intents, so it dominates the volume:
  look at the per-article breakdown line and say so.
- **Basket coverage** (`3/4`) differs when some articles are missing in some languages.
  Then compare growth (`YoY`, `vs wiki`), not levels.
- **Missing articles**: absence is a content gap. A proxy (`--article`) must cover the
  same concept. A broader article (e.g. "therapeutic fasting" for "intermittent
  fasting") measures something else, so mention that when you use it.
- **Disambiguation pages** are never valid articles (`find` marks them).

## What the data cannot tell

- **Willingness to pay** or market size: pageviews measure reading interest, and are a way
  to choose what to validate next (surveys, ads tests, app-store research).
- **Countries**: an edition's readers are spread across countries (see `LIMITS`). English is
  global; Spanish and Portuguese span continents; many people also read English Wikipedia
  in addition to their own language.
- **Search-engine demand**: AI answers and search snippets reduce Wikipedia visits
  unevenly across topics and years. `vs wiki` corrects only for the edition-wide part.
- **Redirects and renames**: views of redirects (old titles) are not added. An article
  renamed inside the window looks new, and the tool flags it as LOW.
- **Remaining bots**: `agent=user` still contains some automated traffic. Spikes and the
  bot-geography check catch the obvious cases, not all of them.

## Output files (per run folder in `wpv-output/`)

- `analysis.json` - every input and computed number, including monthly series.
- `chart.png` - indexed monthly trend per language. With one language, a dashed line shows
  the whole edition.
- `report.pdf`, `report.md` - written by `wpv report`.
