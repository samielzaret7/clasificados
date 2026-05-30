from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from supabase import Client, create_client

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = BASE_DIR / "data"
DEFAULT_ENV_FILE = BASE_DIR / ".env"
DEFAULT_MUNICIPIOS_FILE = BASE_DIR / "PR_Municipios"
REAL_ESTATE_URL = "https://www.clasificadosonline.com/RealEstate.asp"

ROW_SELECTOR = "div.dv-classified-row.dv-classified-row-v2"
NEXT_PAGE_XPATH = '//*[@id="listing"]/table/tbody/tr/td/table/tbody/tr[2]/td/table[5]/tbody/tr[1]/td[3]/div/a'
LATEST_SORT_TEXT = "Ultimos Publicados"


@dataclass
class ScrapeStats:
    total_properties: Optional[int]
    scraped: int
    error_rows: int
    pages_visited: int


@dataclass
class UploadStats:
    properties_updated: int = 0
    properties_uploaded: int = 0
    batches_skipped: int = 0


def info(message: str) -> None:
    print(message, flush=True)


def format_duration(seconds: float) -> str:
    """Convert a duration in seconds to HH:MM:SS string format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining_seconds = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{remaining_seconds:02}"


def jitter_sleep(min_delay: float, max_delay: float) -> None:
    """Sleep for a random duration between min_delay and max_delay for anti-detection."""
    if max_delay <= 0:
        return
    low = max(0.0, min_delay)
    high = max(low, max_delay)
    time.sleep(random.uniform(low, high))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the scraper."""
    parser = argparse.ArgumentParser(description="Scrape Clasificados Online real estate listings")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    parser.add_argument(
        "--chrome-user-data-dir",
        default=os.getenv("CHROME_USER_DATA_DIR", ""),
        help="Path to Chrome user data directory (for cookies/profile state)",
    )
    parser.add_argument(
        "--chrome-profile-directory",
        default=os.getenv("CHROME_PROFILE_DIRECTORY", ""),
        help="Chrome profile directory name inside user data dir (e.g. Default, Profile 1)",
    )
    parser.add_argument("--max-pages", type=int, default=0, help="Max pages to scrape (0 = all)")
    parser.add_argument("--batch-size", type=int, default=500, help="Supabase upload batch size")
    parser.add_argument("--max-retries", type=int, default=5, help="Retry attempts for Supabase operations")
    parser.add_argument("--timeout", type=int, default=20, help="Selenium explicit wait timeout seconds")
    parser.add_argument("--min-delay", type=float, default=0.7, help="Min pacing delay between key actions")
    parser.add_argument("--max-delay", type=float, default=2.0, help="Max pacing delay between key actions")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Directory for CSV outputs and logs")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Path to .env with Supabase credentials")
    parser.add_argument(
        "--municipios-file",
        default=str(DEFAULT_MUNICIPIOS_FILE),
        help="Path to PR municipios mapping file",
    )
    parser.add_argument("--no-upload", action="store_true", help="Skip Supabase upload")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and clean only; no upload")
    return parser.parse_args()


def resolve_chrome_profile_paths(
    chrome_user_data_dir: str,
    chrome_profile_directory: str,
) -> tuple[Optional[Path], str]:
    """Resolve and normalize Chrome user data dir and profile directory paths.

    Handles cases where the profile name is appended to the user data dir path
    and defaults to "Default" when no profile is specified.
    """
    if not chrome_user_data_dir:
        return None, chrome_profile_directory.strip()

    user_data_dir = Path(chrome_user_data_dir).expanduser().resolve()
    profile_directory = chrome_profile_directory.strip()

    # Support passing either ".../Google/Chrome" or ".../Google/Chrome/Default|Profile X".
    if not profile_directory and (user_data_dir.name == "Default" or user_data_dir.name.startswith("Profile ")):
        profile_directory = user_data_dir.name
        user_data_dir = user_data_dir.parent

    if not profile_directory:
        profile_directory = "Default"

    return user_data_dir, profile_directory


def clone_profile_to_temp_user_data_dir(user_data_dir: Path, profile_directory: str) -> tuple[Path, Path]:
    """Clone a Chrome profile to a temp directory to avoid lock conflicts.

    Returns:
        Tuple of (temp_user_data_dir, temp_root) for cleanup later.
    """
    source_profile_dir = user_data_dir / profile_directory
    if not source_profile_dir.exists():
        raise FileNotFoundError(
            f"Chrome profile directory not found: {source_profile_dir}. "
            "Use --chrome-user-data-dir for the parent user data folder and "
            "--chrome-profile-directory for the profile name."
        )

    temp_root = Path(tempfile.mkdtemp(prefix="selenium-chrome-profile-"))
    temp_user_data_dir = temp_root / "user-data"
    temp_user_data_dir.mkdir(parents=True, exist_ok=True)

    local_state_source = user_data_dir / "Local State"
    if local_state_source.exists():
        shutil.copy2(local_state_source, temp_user_data_dir / "Local State")

    ignore = shutil.ignore_patterns(
        "Cache",
        "Code Cache",
        "GPUCache",
        "GrShaderCache",
        "ShaderCache",
        "Crashpad",
        "Singleton*",
        "*.lock",
    )
    shutil.copytree(source_profile_dir, temp_user_data_dir / profile_directory, dirs_exist_ok=True, ignore=ignore)
    return temp_user_data_dir, temp_root


def build_chrome_options(headless: bool, user_data_dir: Optional[Path], profile_directory: str) -> Options:
    """Build Chrome options with headless mode, profile paths, and anti-detection flags."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
    if profile_directory:
        options.add_argument(f"--profile-directory={profile_directory}")
    options.add_argument("--remote-debugging-pipe")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--window-size=1366,900")
    return options


def init_driver(
    headless: bool,
    chrome_user_data_dir: str = "",
    chrome_profile_directory: str = "",
) -> webdriver.Chrome:
    """Initialize a Chrome WebDriver, cloning the profile to a temp dir if locked."""
    user_data_dir, profile_directory = resolve_chrome_profile_paths(
        chrome_user_data_dir=chrome_user_data_dir,
        chrome_profile_directory=chrome_profile_directory,
    )

    if user_data_dir is not None and not user_data_dir.exists():
        raise FileNotFoundError(f"Chrome user data directory not found: {user_data_dir}")

    try:
        options = build_chrome_options(headless=headless, user_data_dir=user_data_dir, profile_directory=profile_directory)
        return webdriver.Chrome(options=options)
    except SessionNotCreatedException as exc:
        message = str(exc)
        if user_data_dir is None or "DevToolsActivePort file doesn't exist" not in message:
            raise

        info("Chrome profile appears locked. Retrying with a temporary cloned profile...")
        temp_user_data_dir, temp_root = clone_profile_to_temp_user_data_dir(user_data_dir, profile_directory)
        retry_options = build_chrome_options(
            headless=headless,
            user_data_dir=temp_user_data_dir,
            profile_directory=profile_directory,
        )
        try:
            driver = webdriver.Chrome(options=retry_options)
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
        setattr(driver, "_temp_profile_root", str(temp_root))
        return driver


def cleanup_temp_profile(driver: webdriver.Chrome) -> None:
    """Remove the temporary cloned Chrome profile directory, if one was created."""
    temp_profile_root = getattr(driver, "_temp_profile_root", "")
    if not temp_profile_root:
        return
    shutil.rmtree(Path(temp_profile_root), ignore_errors=True)


def wait_for_clickable(driver: webdriver.Chrome, locator: tuple[str, str], timeout: int) -> WebElement:
    """Wait until the element matching locator is clickable, then return it."""
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))


def wait_for_presence(driver: webdriver.Chrome, locator: tuple[str, str], timeout: int) -> WebElement:
    """Wait until the element matching locator is present in the DOM, then return it."""
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))


def click_with_pacing(
    driver: webdriver.Chrome,
    locator: tuple[str, str],
    timeout: int,
    min_delay: float,
    max_delay: float,
) -> WebElement:
    """Wait for an element to be clickable, apply a jitter delay, then click it."""
    element = wait_for_clickable(driver, locator, timeout)
    jitter_sleep(min_delay, max_delay)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)
    return element


def detect_block_reason(driver: webdriver.Chrome) -> Optional[str]:
    """Check if the current page is a 403, Access Denied, or CAPTCHA challenge.

    Returns a human-readable reason string if blocked, or None if the page is normal.
    """
    title_text = (driver.title or "").strip().lower()
    current_url = (driver.current_url or "").strip().lower()
    html_text = (driver.page_source or "").lower()

    if "403 forbidden" in title_text or "<h1>403 forbidden" in html_text:
        return "Request blocked by site (403 Forbidden)"
    if "access denied" in title_text or "access denied" in html_text:
        return "Request blocked by site (Access Denied)"

    challenge_markers = (
        "captcha challenge",
        "verify you are human",
        "security check",
        "cf-challenge",
        "hcaptcha",
        "g-recaptcha",
    )
    url_markers = ("captcha", "challenge")

    has_challenge_marker = any(marker in html_text for marker in challenge_markers) or any(
        marker in current_url for marker in url_markers
    )
    if has_challenge_marker:
        # Avoid false positives from passive script/text mentions of CAPTCHA on otherwise normal listing pages.
        has_search_button = bool(driver.find_elements(By.ID, "BtnSearchListing"))
        has_listing_container = bool(driver.find_elements(By.ID, "listing"))
        if not (has_search_button or has_listing_container):
            return "Request challenged with CAPTCHA"

    return None


def select_latest_sort(driver: webdriver.Chrome, timeout: int, min_delay: float, max_delay: float) -> None:
    """Ensure the listing sort dropdown is set to 'Ultimos Publicados' (newest first)."""
    dropdown = wait_for_presence(driver, (By.ID, "jumpMenu"), timeout)
    select = Select(dropdown)

    selected_text = select.first_selected_option.text.strip().lower()
    if LATEST_SORT_TEXT.lower() in selected_text:
        return

    target_text = None
    for option in select.options:
        if LATEST_SORT_TEXT.lower() in option.text.strip().lower():
            target_text = option.text.strip()
            break

    if target_text is None:
        raise RuntimeError("Could not find 'Ultimos Publicados' sorting option")

    jitter_sleep(min_delay, max_delay)
    select.select_by_visible_text(target_text)
    jitter_sleep(max(min_delay, 1.1), max(max_delay, 2.6))


def extract_total_properties(driver: webdriver.Chrome) -> Optional[int]:
    """Extract the total property count displayed on the listing page."""
    locators: Iterable[tuple[str, str]] = (
        (
            By.XPATH,
            '//*[@id="listing"]/table/tbody/tr/td/table/tbody/tr[2]/td/table[4]/tbody/tr/td[2]/div[2]/span',
        ),
        (By.CSS_SELECTOR, "#listing span"),
    )

    for locator in locators:
        elements = driver.find_elements(*locator)
        for element in elements:
            total = parse_total_properties_text(element.text)
            if total is not None:
                return total
    return None


def parse_total_properties_text(raw_text: str) -> Optional[int]:
    """Parse a numeric property count from raw text like '9,757 Propiedades'."""
    text = (raw_text or "").strip()
    if not text:
        return None

    matches = re.findall(r"\d+[\d,\.]*", text)
    if not matches:
        return None

    candidate = matches[-1].replace(",", "").replace(".", "")
    if not candidate.isdigit():
        return None
    return int(candidate)


def first_text(root: WebElement, selectors: Iterable[str]) -> str:
    """Return the text of the first element matching any selector, or empty string."""
    for selector in selectors:
        try:
            element = root.find_element(By.CSS_SELECTOR, selector)
            text = element.text.strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def first_attr(root: WebElement, selectors: Iterable[str], attr_name: str) -> str:
    """Return the attribute value of the first element matching any selector, or empty string."""
    for selector in selectors:
        try:
            element = root.find_element(By.CSS_SELECTOR, selector)
            value = (element.get_attribute(attr_name) or "").strip()
            if value:
                return value
        except Exception:
            continue
    return ""


def extract_property_id(link: str) -> Optional[str]:
    """Extract the numeric property ID from a listing URL (e.g. '...ID=12345')."""
    match = re.search(r"ID=(\d+)", link or "")
    return match.group(1) if match else None


def parse_property_row(row: WebElement) -> Optional[dict[str, Any]]:
    """Parse a single property listing row element into a dict of field values.

    Returns None if no valid property ID can be extracted from the row.
    """
    link = first_attr(
        row,
        (
            "td:nth-child(2) table tbody tr:nth-child(1) td a",
            "a[href*='RE_Detail']",
            "a[href*='ID=']",
        ),
        "href",
    )
    property_id = extract_property_id(link)
    if not property_id:
        return None

    title = first_text(
        row,
        (
            "td:nth-child(2) > table > tbody > tr:nth-child(1) > td > a > div > span",
            "td:nth-child(2) table tbody tr:nth-child(1) td a",
        ),
    )
    price = first_text(
        row,
        (
            "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(2) > font",
            "span span font",
        ),
    )
    rooms = first_text(
        row,
        (
            "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(1) > span",
            "td:nth-child(2) > table > tbody > tr:nth-child(2) span",
        ),
    )
    listing_type = first_text(
        row,
        (
            "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(4)",
            "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1)",
        ),
    )
    type_extra = first_text(
        row,
        ("td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(5)",),
    )
    if type_extra and type_extra not in listing_type:
        listing_type = f"{listing_type} {type_extra}".strip()

    barrio = ""
    pueblo = ""
    location_links = row.find_elements(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(3) > td > a")
    if location_links:
        barrio = location_links[0].text.strip() if len(location_links) >= 1 else ""
        pueblo = location_links[-1].text.strip() if len(location_links) >= 2 else ""

    piclink = first_attr(
        row,
        (
            "td:nth-child(1) > table > tbody > tr > td > div > a > img",
            "img",
        ),
        "src",
    )

    optioned = "optioned" in row.text.lower()

    broker = "No Broker"
    if "MultipleSellers" in link:
        broker = "Multiple Sellers"
    else:
        broker_alt = first_attr(
            row,
            ("td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(2) > center > a > img",),
            "alt",
        )
        if broker_alt:
            broker = broker_alt

    return {
        "propertyid": property_id,
        "title": title,
        "price": price,
        "rooms": rooms,
        "type": listing_type,
        "barrio": barrio,
        "pueblo": pueblo,
        "link": link,
        "piclink": piclink,
        "broker": broker,
        "optioned": optioned,
    }


def click_next_page(
    driver: webdriver.Chrome,
    first_row: Optional[WebElement],
    timeout: int,
    min_delay: float,
    max_delay: float,
) -> bool:
    """Click the next-page link and wait for the page to transition.

    Returns True if navigation succeeded, False if no next page is available.
    """
    candidates: list[WebElement] = []

    for locator in [
        (By.XPATH, NEXT_PAGE_XPATH),
        (
            By.XPATH,
            "//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next') "
            "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'siguiente')]",
        ),
    ]:
        candidates.extend(driver.find_elements(*locator))

    candidate = next((element for element in candidates if element.is_displayed() and element.is_enabled()), None)
    if candidate is None:
        return False

    jitter_sleep(min_delay, max_delay)
    try:
        candidate.click()
    except Exception:
        driver.execute_script("arguments[0].click();", candidate)

    if first_row is not None:
        try:
            WebDriverWait(driver, timeout).until(EC.staleness_of(first_row))
        except TimeoutException:
            return False

    return True


def scrape_properties(driver: webdriver.Chrome, args: argparse.Namespace) -> tuple[pd.DataFrame, ScrapeStats]:
    """Scrape all property listings from clasificadosonline.com.

    Navigates to the site, sets sort order, and iterates through pages
    collecting property data. Returns a DataFrame and scrape statistics.
    """
    info(f"Scrape started at {datetime.now().strftime('%H:%M:%S')}")

    driver.get(REAL_ESTATE_URL)

    block_reason = detect_block_reason(driver)
    if block_reason:
        raise RuntimeError(f"{block_reason}. URL: {driver.current_url}")

    if driver.find_elements(By.ID, "BtnSearchListing"):
        click_with_pacing(driver, (By.ID, "BtnSearchListing"), args.timeout, args.min_delay, args.max_delay)
    else:
        info("BtnSearchListing not found; attempting direct listing mode")

    block_reason = detect_block_reason(driver)
    if block_reason:
        raise RuntimeError(f"{block_reason}. URL: {driver.current_url}")

    select_latest_sort(driver, args.timeout, args.min_delay, args.max_delay)

    total_properties = extract_total_properties(driver)
    seen_properties: set[str] = set()
    all_properties: list[dict[str, Any]] = []
    error_rows = 0
    pages_visited = 0

    while True:
        pages_visited += 1

        try:
            WebDriverWait(driver, args.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ROW_SELECTOR))
            )
        except TimeoutException:
            info(f"No listing rows found for page {pages_visited}; stopping scrape")
            break

        rows = driver.find_elements(By.CSS_SELECTOR, ROW_SELECTOR)
        if not rows:
            info("No more rows found; stopping scrape")
            break

        added_this_page = 0
        for row in rows:
            try:
                item = parse_property_row(row)
                if item is None:
                    error_rows += 1
                    continue

                property_id = item["propertyid"]
                if property_id in seen_properties:
                    continue

                seen_properties.add(property_id)
                all_properties.append(item)
                added_this_page += 1
            except Exception:
                error_rows += 1

        info(f"Scraping page {pages_visited}: rows={len(rows)}, new_properties={added_this_page}")

        if args.max_pages > 0 and pages_visited >= args.max_pages:
            info(f"Reached max page limit ({args.max_pages}); stopping scrape")
            break

        first_row = rows[0] if rows else None
        if not click_next_page(driver, first_row, args.timeout, args.min_delay, args.max_delay):
            info("No next page available")
            break

        select_latest_sort(driver, args.timeout, args.min_delay, args.max_delay)

    scraped_df = pd.DataFrame(all_properties)
    stats = ScrapeStats(
        total_properties=total_properties,
        scraped=len(scraped_df),
        error_rows=error_rows,
        pages_visited=pages_visited,
    )
    return scraped_df, stats


def clean_broker_name(broker_name: Any, barrio_name: Any) -> str:
    """Clean a broker name by removing site prefix, barrio artifacts, and 'de' prefixes."""
    broker_cleaned = str(broker_name or "").replace("ClasificadosOnline", "").strip()
    barrio_text = str(barrio_name or "")

    try:
        if "-" in barrio_text:
            barrio_piece = barrio_text.split("-", 1)[1].replace("-", " ").strip()
            if barrio_piece:
                broker_cleaned = re.sub(re.escape(barrio_piece), "", broker_cleaned, flags=re.IGNORECASE).strip()

        if broker_cleaned.lower().startswith("de "):
            broker_cleaned = broker_cleaned[3:]
        if broker_cleaned.lower().endswith(" de"):
            broker_cleaned = broker_cleaned[:-3]
    except Exception:
        pass

    return broker_cleaned.strip() or "No Broker"


def load_municipios(municipios_file: Path) -> pd.DataFrame:
    """Load the PR municipios CSV and validate required columns ('name', 'region')."""
    municipio = pd.read_csv(municipios_file)
    required_columns = {"name", "region"}
    missing_columns = required_columns.difference(set(municipio.columns))
    if missing_columns:
        raise ValueError(f"Municipios file missing required columns: {sorted(missing_columns)}")
    return municipio


def clean_real_estate_data(df: pd.DataFrame, municipio_df: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize scraped property data.

    Strips type prefixes, cleans broker names, extracts bedrooms/bathrooms,
    maps pueblos to regions, converts prices, and deduplicates.
    """
    if df.empty:
        return df

    cleaned = df.copy()

    cleaned["type"] = cleaned["type"].astype(str).str.replace(r"^,\s*", "", regex=True).str.strip()
    cleaned["broker"] = cleaned.apply(lambda row: clean_broker_name(row.get("broker"), row.get("barrio")), axis=1)

    rooms_source = cleaned["rooms"].astype(str)
    cleaned["bedrooms"] = rooms_source.str.extract(r"(>=\s*\d+|\d+)\s+Cuartos", expand=False).fillna("0")
    cleaned["bathrooms"] = rooms_source.str.extract(r"(>=\s*\d+|\d+)\s+Baños", expand=False).fillna("0")

    if "rooms" in cleaned.columns:
        cleaned = cleaned.drop(columns=["rooms"])

    cleaned["barrio"] = cleaned["barrio"].fillna("").astype(str).str.strip()
    cleaned["pueblo"] = cleaned["pueblo"].fillna("").astype(str).str.strip()

    municipio_names = [str(name).strip() for name in municipio_df["name"].dropna().tolist()]
    municipio_lookup = {str(name).strip(): region for name, region in zip(municipio_df["name"], municipio_df["region"]) }

    def match_municipio_name(pueblo_value: str) -> Optional[str]:
        pueblo_lower = str(pueblo_value).lower()
        for municipio_name in municipio_names:
            if municipio_name and municipio_name.lower() in pueblo_lower:
                return municipio_name
        return None

    cleaned["pueblo_name"] = cleaned["pueblo"].apply(match_municipio_name)
    cleaned["region"] = cleaned["pueblo_name"].map(municipio_lookup)
    cleaned = cleaned.drop(columns=["pueblo_name"])

    cleaned["price"] = pd.to_numeric(
        cleaned["price"].astype(str).str.replace(r"[^\d.]", "", regex=True),
        errors="coerce",
    )

    invalid_prices = int(cleaned["price"].isna().sum())
    if invalid_prices:
        info(f"Warning: {invalid_prices} rows have non-numeric price after cleanup")

    duplicates = cleaned[cleaned.duplicated(subset=["propertyid"], keep=False)]
    if not duplicates.empty:
        duplicate_count = duplicates["propertyid"].nunique()
        info(f"Duplicate properties found: {duplicate_count}")
        preview = duplicates.head(10)
        info(f"Duplicate preview (first {len(preview)} rows):")
        info(preview.to_string(index=False))
    else:
        info("No duplicate properties found")

    cleaned = cleaned.drop_duplicates(subset=["propertyid"], keep="first").reset_index(drop=True)

    return cleaned


def validate_cleaned_data(df: pd.DataFrame) -> dict[str, int]:
    """Return a validation report with counts of missing fields and duplicates."""
    if df.empty:
        return {
            "rows": 0,
            "missing_property_id": 0,
            "missing_title": 0,
            "missing_link": 0,
            "invalid_price": 0,
            "duplicate_property_id": 0,
        }

    report = {
        "rows": len(df),
        "missing_property_id": int(df["propertyid"].isna().sum() + (df["propertyid"].astype(str).str.strip() == "").sum()),
        "missing_title": int(df["title"].isna().sum() + (df["title"].astype(str).str.strip() == "").sum()),
        "missing_link": int(df["link"].isna().sum() + (df["link"].astype(str).str.strip() == "").sum()),
        "invalid_price": int(df["price"].isna().sum()),
        "duplicate_property_id": int(df["propertyid"].duplicated().sum()),
    }
    return report


def get_supabase_client(env_file: Path) -> Client:
    """Load credentials from the .env file and return an initialized Supabase client."""
    load_dotenv(env_file)
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment")

    return create_client(supabase_url, supabase_key)


def fetch_last_scrape_date(supabase: Client, max_retries: int) -> date:
    """Fetch the most recent scrape date from the scraping_log table with retries."""
    fallback = datetime.now().date()

    for attempt in range(1, max_retries + 1):
        try:
            response = (
                supabase.table("scraping_log")
                .select("date")
                .order("date", desc=True)
                .limit(1)
                .execute()
            )
            data = response.data or []
            if data and data[0].get("date"):
                return datetime.strptime(data[0]["date"], "%Y-%m-%d").date()
            return fallback
        except Exception as exc:
            wait_seconds = min(2 ** attempt, 30)
            info(f"Retry {attempt}/{max_retries} fetching last scrape date due to: {exc}")
            time.sleep(wait_seconds)

    return fallback


def chunk_dataframe(df: pd.DataFrame, batch_size: int) -> list[pd.DataFrame]:
    """Split a DataFrame into a list of smaller DataFrames of at most batch_size rows."""
    if df.empty:
        return []
    size = max(batch_size, 1)
    return [df.iloc[start : start + size] for start in range(0, len(df), size)]


def row_to_insert_payload(row: pd.Series, today_text: str) -> dict[str, Any]:
    """Build a Supabase insert payload for a new property."""
    return {
        "property_id": str(row["propertyid"]),
        "title": str(row.get("title", "")),
        "price": None if pd.isna(row.get("price")) else float(row["price"]),
        "price_changed": False,
        "previous_price": None,
        "type": str(row.get("type", "")),
        "barrio": str(row.get("barrio", "")),
        "pueblo": str(row.get("pueblo", "")),
        "link": str(row.get("link", "")),
        "broker": str(row.get("broker", "")),
        "piclink": str(row.get("piclink", "")),
        "bedrooms": str(row.get("bedrooms", "0")),
        "bathrooms": str(row.get("bathrooms", "0")),
        "region": None if pd.isna(row.get("region")) else str(row.get("region", "")),
        "optioned": bool(row.get("optioned", False)),
        "first_seen": today_text,
        "last_seen": today_text,
        "times_seen": 1,
    }


def row_to_update_payload(
    row: pd.Series,
    existing: dict[str, Any],
    today_text: str,
    days_since_last_scrape: int,
) -> Optional[dict[str, Any]]:
    """Build a Supabase upsert payload for an existing property.

    Detects price changes and increments times_seen by days_since_last_scrape.
    Returns None if the property was already updated today.
    """
    property_id = str(row["propertyid"])
    existing_last_seen = str(existing.get("last_seen") or "")
    if existing_last_seen == today_text:
        return None

    db_price_raw = existing.get("price")
    scraped_price = None if pd.isna(row.get("price")) else float(row["price"])

    price_changed = False
    previous_price = existing.get("previous_price")
    if db_price_raw is not None and scraped_price is not None:
        try:
            db_price = float(db_price_raw)
            if db_price != scraped_price:
                price_changed = True
                previous_price = db_price
        except Exception:
            if db_price_raw != scraped_price:
                price_changed = True
                previous_price = db_price_raw

    times_seen_increment = max(days_since_last_scrape, 1)
    current_times_seen = int(existing.get("times_seen") or 0)

    return {
        "property_id": property_id,
        "title": str(row.get("title", "")),
        "price": scraped_price,
        "price_changed": bool(existing.get("price_changed", False) or price_changed),
        "previous_price": previous_price,
        "type": str(row.get("type", "")),
        "barrio": str(row.get("barrio", "")),
        "pueblo": str(row.get("pueblo", "")),
        "link": str(row.get("link", "")),
        "broker": str(row.get("broker", "")),
        "piclink": str(row.get("piclink", "")),
        "bedrooms": str(row.get("bedrooms", "0")),
        "bathrooms": str(row.get("bathrooms", "0")),
        "region": None if pd.isna(row.get("region")) else str(row.get("region", "")),
        "optioned": bool(row.get("optioned", False)),
        "first_seen": str(existing.get("first_seen") or today_text),
        "last_seen": today_text,
        "times_seen": current_times_seen + times_seen_increment,
    }


def upload_properties_to_database(
    df: pd.DataFrame,
    supabase: Client,
    batch_size: int = 500,
    max_retries: int = 5,
    output_dir: Path = DEFAULT_LOG_DIR,
) -> UploadStats:
    """Upload cleaned properties to Supabase in batches with exponential-backoff retries.

    Inserts new properties and upserts existing ones. Skipped batches
    (after max retries) are saved to a CSV in output_dir.
    """
    stats = UploadStats()
    if df.empty:
        info("No rows to upload")
        return stats

    today_date = datetime.now().date()
    today_text = str(today_date)
    last_scrape_date = fetch_last_scrape_date(supabase, max_retries=max_retries)
    days_since_last_scrape = max((today_date - last_scrape_date).days, 1)

    skipped_batches: list[pd.DataFrame] = []
    batches = chunk_dataframe(df, batch_size)

    for batch_index, batch in enumerate(batches, start=1):
        for attempt in range(1, max_retries + 1):
            try:
                info(f"Processing batch {batch_index}/{len(batches)}")

                property_ids = batch["propertyid"].dropna().astype(str).tolist()
                if not property_ids:
                    break

                existing_response = (
                    supabase.table("properties")
                    .select(
                        "property_id,price,price_changed,previous_price,optioned,last_seen,times_seen,first_seen"
                    )
                    .in_("property_id", property_ids)
                    .execute()
                )

                existing_data = {
                    str(item["property_id"]): item for item in (existing_response.data or []) if item.get("property_id")
                }

                payload: list[dict[str, Any]] = []

                for _, row in batch.iterrows():
                    property_id = str(row["propertyid"])
                    existing = existing_data.get(property_id)
                    if existing:
                        update_row = row_to_update_payload(
                            row,
                            existing,
                            today_text=today_text,
                            days_since_last_scrape=days_since_last_scrape,
                        )
                        if update_row is not None:
                            payload.append(update_row)
                            stats.properties_updated += 1
                    else:
                        payload.append(row_to_insert_payload(row, today_text=today_text))
                        stats.properties_uploaded += 1

                if payload:
                    supabase.table("properties").upsert(payload, on_conflict="property_id").execute()

                break
            except Exception as exc:
                wait_seconds = min(2 ** attempt, 30)
                info(
                    f"Retry {attempt}/{max_retries} for batch {batch_index} due to error: {exc}. "
                    f"Sleeping {wait_seconds}s"
                )
                time.sleep(wait_seconds)
        else:
            info(f"Skipping batch {batch_index} after {max_retries} failed attempts")
            stats.batches_skipped += 1
            skipped_batches.append(batch)

    if skipped_batches:
        skipped_df = pd.concat(skipped_batches, ignore_index=True)
        skipped_path = output_dir / f"skipped_batches_{today_text}.csv"
        skipped_df.to_csv(skipped_path, index=False)
        info(f"Saved skipped batches to {skipped_path}")

    info(f"Properties updated: {stats.properties_updated}")
    info(f"Properties uploaded: {stats.properties_uploaded}")
    info(f"Batches skipped: {stats.batches_skipped}")

    return stats


def log_scraping_results(
    log_dir: Path,
    scrape_start: datetime,
    scrape_end: datetime,
    scrape_stats: ScrapeStats,
    upload_start: Optional[datetime] = None,
    upload_end: Optional[datetime] = None,
    upload_stats: Optional[UploadStats] = None,
    supabase: Optional[Client] = None,
) -> None:
    """Append a run summary row to the local CSV log and optionally to Supabase."""
    log_dir.mkdir(parents=True, exist_ok=True)

    row: dict[str, Any] = {
        "date": datetime.now().date().strftime("%Y-%m-%d"),
        "scrape_start": scrape_start.strftime("%H:%M:%S"),
        "scrape_end": scrape_end.strftime("%H:%M:%S"),
        "scrape_time": format_duration((scrape_end - scrape_start).total_seconds()),
        "total_properties": scrape_stats.total_properties,
        "scraped": scrape_stats.scraped,
        "error_rows": scrape_stats.error_rows,
        "pages_visited": scrape_stats.pages_visited,
    }

    if upload_start and upload_end and upload_stats:
        row.update(
            {
                "upload_start": upload_start.strftime("%H:%M:%S"),
                "upload_end": upload_end.strftime("%H:%M:%S"),
                "upload_time": format_duration((upload_end - upload_start).total_seconds()),
                "total_time": format_duration((upload_end - scrape_start).total_seconds()),
                "updated": upload_stats.properties_updated,
                "uploaded": upload_stats.properties_uploaded,
                "batches_skipped": upload_stats.batches_skipped,
            }
        )

    log_file = log_dir / "scraping_log.csv"
    write_header = not log_file.exists()
    pd.DataFrame([row]).to_csv(log_file, mode="a", header=write_header, index=False)
    info(f"Scraping log saved to CSV: {log_file}")

    if supabase is not None and upload_start and upload_end and upload_stats:
        try:
            supabase.table("scraping_log").insert(row).execute()
            info("Scraping log uploaded to Supabase")
        except Exception as exc:
            info(f"Error uploading scraping log: {exc}")


def run() -> int:
    """Main entry point: parse args, scrape, clean, validate, upload, and log results."""
    args = parse_args()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    municipios_file = Path(args.municipios_file)

    scrape_start = datetime.now()
    upload_start: Optional[datetime] = None
    upload_end: Optional[datetime] = None
    upload_stats: Optional[UploadStats] = None
    supabase: Optional[Client] = None

    driver: Optional[webdriver.Chrome] = None

    try:
        municipio_df = load_municipios(municipios_file)
        driver = init_driver(
            headless=args.headless,
            chrome_user_data_dir=args.chrome_user_data_dir,
            chrome_profile_directory=args.chrome_profile_directory,
        )

        raw_df, scrape_stats = scrape_properties(driver, args)
        info(f"Scraped {scrape_stats.scraped} properties")
        info(f"Rows with extraction errors: {scrape_stats.error_rows}")

        cleaned_df = clean_real_estate_data(raw_df, municipio_df)

        validation = validate_cleaned_data(cleaned_df)
        info(f"Validation summary: {validation}")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        data_path = log_dir / f"classifieds_data_{timestamp}.csv"
        cleaned_df.to_csv(data_path, index=False)
        info(f"Cleaned data saved to {data_path}")

        scrape_end = datetime.now()

        if args.dry_run or args.no_upload:
            info("Upload skipped due to --dry-run/--no-upload")
        else:
            upload_start = datetime.now()
            info(f"Upload started at {upload_start.strftime('%H:%M:%S')}")

            supabase = get_supabase_client(Path(args.env_file))
            upload_stats = upload_properties_to_database(
                cleaned_df,
                supabase,
                batch_size=args.batch_size,
                max_retries=args.max_retries,
                output_dir=log_dir,
            )

            upload_end = datetime.now()
            info(f"Upload finished at {upload_end.strftime('%H:%M:%S')}")

        log_scraping_results(
            log_dir=log_dir,
            scrape_start=scrape_start,
            scrape_end=scrape_end,
            scrape_stats=scrape_stats,
            upload_start=upload_start,
            upload_end=upload_end,
            upload_stats=upload_stats,
            supabase=supabase,
        )

        info(f"Scrape finished at {scrape_end.strftime('%H:%M:%S')}")

        if upload_start and upload_end:
            info(
                "Run timing summary: "
                f"scrape={format_duration((scrape_end - scrape_start).total_seconds())}, "
                f"upload={format_duration((upload_end - upload_start).total_seconds())}, "
                f"total={format_duration((upload_end - scrape_start).total_seconds())}"
            )

        return 0
    except Exception as exc:
        info(f"Run failed: {exc}")
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            finally:
                cleanup_temp_profile(driver)


if __name__ == "__main__":
    raise SystemExit(run())
