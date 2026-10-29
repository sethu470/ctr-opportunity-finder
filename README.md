# CTR Opportunity Finder

Finds pages and queries that rank on or near page 1 but earn fewer clicks than their position normally would, then ranks them by **estimated extra clicks** so you know which titles and meta descriptions to fix first.

## Why it exists

Looking at impressions and rankings alone treats every page as equal priority. This turns Search Console data into a short, ranked to-do list, and separates two different problems:

- **Position 4-10 with weak CTR:** a snippet problem. Rewrite the title or meta description.
- **Position 11-15:** a ranking problem. CTR improves only after the page reaches page 1, so fix content and internal links first.

## Setup

```bash
pip install pandas
# API mode only:
pip install google-api-python-client google-auth
```

## Usage

**Option 1: CSV export (quickest)**

1. In Search Console, open Performance > Search results, set the date range (3 months works well), and export.
2. Run:

```bash
python ctr_opportunity_finder.py --input Pages.csv --min-impressions 100
```

A Queries export works too, and you can pass one file at a time.

**Option 2: API (page + query level)**

1. Create a service account, download its JSON key, and add its email as a user on your Search Console property.
2. Run:

```bash
python ctr_opportunity_finder.py \
  --site sc-domain:example.com \
  --creds service-account.json \
  --days 90 \
  --brand-terms "yourbrand,your brand"
```

Page + query rows tell you which query a page should target in its title.

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--pos-min` / `--pos-max` | 4 / 15 | Position range to analyse |
| `--min-impressions` | 100 | Ignore low-volume rows |
| `--quantile` | 0.5 | Benchmark = this quantile of your own CTR at that position (0.5 = median; try 0.75 for a stricter target) |
| `--min-rows` | 5 | Rows needed at a position before trusting your own data |
| `--brand-terms` | none | Excluded from query rows (brand queries behave differently) |
| `--top` | 25 | Rows printed to the terminal |
| `--output` | ctr_opportunities.csv | Results file |

## How it works

1. Cleans the data and recomputes CTR as clicks / impressions.
2. Builds an expected CTR for each rounded position from **your own site's data**. If a position has too few rows, it falls back to a rough generic curve (flagged in the `benchmark` column).
3. Filters to the position range and minimum impressions.
4. Estimated extra clicks = impressions x (expected CTR - actual CTR), floored at zero.
5. Ranks by that estimate and tags each row with the likely lever.

## Limitations

- Estimates only. They prioritise where to look; they do not forecast results.
- Benchmarks come from your own data, so a small site gives a noisier baseline. Raise `--min-rows` or use a longer date range.
- Averaged positions hide ranking volatility, and SERP features (featured snippets, AI answers) change CTR in ways this does not model.
- It does not prove that a change caused a lift. Log what you change and when, and compare against untouched pages afterwards (a natural next step).

## Suggested workflow

1. Run on 90 days of data, excluding brand terms.
2. Take the top 10-20 snippet fixes and rewrite titles/meta descriptions.
3. Record the change date and URLs.
4. Re-run after 4-6 weeks and compare CTR for the changed rows.
