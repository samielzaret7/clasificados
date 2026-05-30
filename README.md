# Clasificados Online Real Estate Scraper

A Python web scraper that extracts real estate listings from [clasificadosonline.com](https://www.clasificadosonline.com/), cleans the data, and syncs it to a Supabase database.

## Features

- Scrapes all real estate listing pages with automatic pagination
- Sorts by "Ultimos Publicados" (newest first) and re-validates sort on every page
- Anti-detection: randomized delays via `jitter_sleep()`, automation flag disabling
- Chrome profile cloning to avoid lock conflicts when Chrome is already open
- Block detection for 403 Forbidden, Access Denied, and CAPTCHA challenges
- Resilient element extraction using multiple CSS selector fallbacks (`first_text`/`first_attr`)
- Data cleaning: broker name normalization, bedroom/bathroom extraction, municipio-to-region mapping, price parsing, deduplication
- Batch upload to Supabase with exponential-backoff retries
- Price change tracking (`price_changed`, `previous_price` fields)
- `times_seen` incremented by days since last scrape (approximates listing age)
- Timestamped CSV output and structured logging (local CSV + Supabase)
- `--dry-run` and `--no-upload` modes for testing without database writes

## Prerequisites

- Python 3.9+
- Google Chrome
- ChromeDriver (matching your Chrome version)

## Setup

```bash
# Clone the repository
git clone https://github.com/samielzaret7/Clasificados-Online-Real-Estate-Scraper.git
cd Clasificados-Online-Real-Estate-Scraper

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file from the example
cp .env.example .env
# Edit .env with your Supabase credentials
```

## Usage

### Dry run (scrape + clean, no upload)

```bash
python clasificados_scrape.py --headless --dry-run
```

### One-page smoke test

```bash
python clasificados_scrape.py --headless --max-pages 1 --dry-run
```

### Full run with Supabase upload

```bash
python clasificados_scrape.py --headless
```

### Run with Chrome visible

```bash
python clasificados_scrape.py --max-pages 3
```

### Use a specific Chrome profile (to reuse cookies)

```bash
python clasificados_scrape.py --headless \
  --chrome-user-data-dir ~/Library/Application\ Support/Google/Chrome \
  --chrome-profile-directory "Default"
```

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--headless` | off | Run Chrome in headless mode |
| `--chrome-user-data-dir` | `""` | Path to Chrome user data directory |
| `--chrome-profile-directory` | `""` | Chrome profile name (e.g. `Default`, `Profile 1`) |
| `--max-pages` | `0` (all) | Limit number of pages to scrape |
| `--batch-size` | `500` | Supabase upload batch size |
| `--max-retries` | `5` | Retry attempts for Supabase operations |
| `--timeout` | `20` | Selenium explicit wait timeout (seconds) |
| `--min-delay` | `0.7` | Minimum pacing delay between key actions (seconds) |
| `--max-delay` | `2.0` | Maximum pacing delay between key actions (seconds) |
| `--log-dir` | `data/` | Directory for CSV outputs and logs |
| `--env-file` | `.env` | Path to `.env` with Supabase credentials |
| `--municipios-file` | `PR_Municipios` | Path to municipios mapping CSV |
| `--no-upload` | off | Skip Supabase upload |
| `--dry-run` | off | Scrape and clean only; no upload |

## Project Structure

```
Clasificados-Online-Real-Estate-Scraper/
├── clasificados_scrape.py       # Main scraper script (entry point: run())
├── clasificados_scrape.ipynb    # Development notebook (exploratory)
├── PR_Municipios                # CSV mapping 78 PR municipalities to regions
├── requirements.txt             # Python dependencies
├── .env.example                 # Template for Supabase credentials
├── .env                         # Your credentials (gitignored)
├── .gitignore
├── CLAUDE.md                    # Claude Code project instructions
├── README.md
├── tests/
│   ├── test_clasificados_scrape_utils.py  # Unit tests
│   └── test_scrape_integration.py         # Integration tests (requires Chrome)
└── data/                        # Gitignored output directory
    ├── classifieds_data_<timestamp>.csv
    ├── scraping_log.csv
    └── skipped_batches_<date>.csv
```

## Architecture

The scraper follows a linear pipeline:

```
Scrape --> Clean --> Validate --> Save CSV --> Upload --> Log
```

1. **Scrape** (`scrape_properties`): Opens Chrome, navigates to the listing page, clicks "Ver Listado", sets sort order, and iterates through all pages. Each property row is parsed by `parse_property_row()` which uses `first_text()`/`first_attr()` helpers that try multiple CSS selectors for resilience against minor HTML changes.

2. **Clean** (`clean_real_estate_data`): Normalizes raw data -- strips type prefixes, cleans broker names, extracts bedrooms/bathrooms from room strings, maps pueblos to regions via the PR_Municipios file, converts prices to float, and deduplicates.

3. **Validate** (`validate_cleaned_data`): Produces a report of missing property IDs, titles, links, invalid prices, and remaining duplicates.

4. **Save CSV**: Writes a timestamped CSV to `data/`.

5. **Upload** (`upload_properties_to_database`): Syncs to Supabase in configurable batches. For each batch, fetches existing records and builds upsert payloads. New properties are inserted; existing ones are updated with new `last_seen`, incremented `times_seen`, and price change tracking. Failed batches after max retries are saved to a CSV.

6. **Log** (`log_scraping_results`): Appends a summary row to `data/scraping_log.csv` and inserts into the Supabase `scraping_log` table.

## Supabase Schema

### `properties` table

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | text (PK) | Listing ID from clasificadosonline |
| `title` | text | Property title |
| `price` | float | Listed price (USD) |
| `price_changed` | boolean | Whether price has ever changed |
| `previous_price` | float | Last known different price |
| `type` | text | Property type (e.g. "Casa", "Apartamento") |
| `barrio` | text | Neighborhood |
| `pueblo` | text | Municipality |
| `link` | text | Full URL to the listing |
| `broker` | text | Broker/agent name |
| `piclink` | text | Thumbnail image URL |
| `bedrooms` | text | Number of bedrooms |
| `bathrooms` | text | Number of bathrooms |
| `region` | text | Geographic region (metro, north, south, east, west) |
| `optioned` | boolean | Whether property is under option |
| `first_seen` | date | Date first scraped |
| `last_seen` | date | Date last scraped |
| `times_seen` | integer | Approximate days listed |

### `scraping_log` table

| Column | Type | Description |
|--------|------|-------------|
| `date` | date | Scrape date |
| `scrape_start` | time | Scrape start time |
| `scrape_end` | time | Scrape end time |
| `scrape_time` | text | Scrape duration (HH:MM:SS) |
| `total_properties` | integer | Total properties on site |
| `scraped` | integer | Properties successfully scraped |
| `error_rows` | integer | Rows that failed extraction |
| `upload_start` | time | Upload start time |
| `upload_end` | time | Upload end time |
| `upload_time` | text | Upload duration (HH:MM:SS) |
| `total_time` | text | Total run duration (HH:MM:SS) |
| `updated` | integer | Properties updated |
| `uploaded` | integer | New properties inserted |
| `batches_skipped` | integer | Batches that failed after retries |

## Testing

```bash
# Unit tests (no Chrome or network required)
python -m pytest tests/test_clasificados_scrape_utils.py -v

# Integration tests (requires Chrome + network)
python tests/test_scrape_integration.py
python tests/test_scrape_integration.py --validate
python tests/test_scrape_integration.py --test-upload
```

## Notes

- **`times_seen` logic**: Incremented by `days_since_last_scrape` rather than 1, so it approximates the number of days a property has been continuously listed.
- **Sort validation**: The "Ultimos Publicados" sort order is re-checked on every page because the dropdown can reset after navigation.
- **Anti-detection**: `jitter_sleep()` adds randomized delays between actions. The `--disable-blink-features=AutomationControlled` flag is set on Chrome.
- **Profile cloning**: If Chrome is already running and the profile is locked, the scraper automatically clones the profile to a temp directory and cleans it up on exit.
- **Multiple sellers**: Properties with "MultipleSellers" in the URL get `broker = "Multiple Sellers"` instead of trying to parse the broker image.
- **Python version**: The codebase uses `from __future__ import annotations` for forward-compatible type hints but avoids `str | None` syntax to maintain Python 3.9 compatibility.

## Related Projects

- **[PropertyScout](https://github.com/samielzaret7/PropertyScout)** — Public-facing Puerto Rico real estate market dashboard (search, analytics, KPIs) powered by the data this scraper collects.
- **[Agent-Dashboard](https://github.com/samielzaret7/Agent-Dashboard)** — Agent-facing dashboard with authentication and property assignment, sharing the same Supabase backend.
