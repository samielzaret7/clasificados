import base64
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException


def extract_property_id(link):
    match = re.search(r"ID=(\d+)", link)
    return match.group(1) if match else None


def set_sort_order(driver):
    dropdown_element = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, '//*[@id="jumpMenu"]'))
    )
    select = Select(dropdown_element)
    if select.first_selected_option.text != 'Ultimos Publicados (Más Recientes Primeros)':
        dropdown_element.click()
        time.sleep(2)
        driver.find_element(By.XPATH, '//*[@id="jumpMenu"]/option[7]').click()
        time.sleep(7)


def main():
    options = Options()
    driver = webdriver.Chrome(options=options)

    all_properties = []

    try:
        driver.get('https://www.clasificadosonline.com/RealEstate.asp')

        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="BtnSearchListing"]'))
        ).click()

        set_sort_order(driver)

        for page_number in range(1, 3):
            print(f"Scraping page {page_number}...")

            set_sort_order(driver)

            property_rows = driver.find_elements(
                By.CSS_SELECTOR,
                "#listing table tbody tr td table tbody tr:nth-child(2) td div.dv-classified-row.dv-classified-row-v2"
            )

            for row in property_rows:
                try:
                    link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) table tbody tr:nth-child(1) > td > a")
                    link = link_element.get_attribute("href")
                    property_id = extract_property_id(link)

                    property_data = {
                        "propertyid": property_id,
                        "title": row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(1) > td > a > div > span").text,
                        "price": row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(2) > font").text,
                        "rooms": row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(1) > span").text,
                        "type": row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(4)").text,
                        "barrio": row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(3) > td > a:nth-child(1)").text,
                        "pueblo": row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(3) > td > a:nth-child(3)").text,
                        "link": link,
                        "piclink": row.find_element(By.CSS_SELECTOR, "td:nth-child(1) > table > tbody > tr > td > div > a > img").get_attribute("src"),
                        "optioned": False,
                        "page": page_number,
                    }

                    try:
                        type_2 = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(5)").text
                        property_data["type"] += f" {type_2}"
                    except NoSuchElementException:
                        pass

                    try:
                        optioned_text = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(6)").text
                        if "Optioned" in optioned_text:
                            property_data["optioned"] = True
                    except NoSuchElementException:
                        pass

                    if "MultipleSellers" in property_data["link"]:
                        property_data["broker"] = "Multiple Sellers"
                    else:
                        try:
                            property_data["broker"] = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(2) > center > a > img").get_attribute("alt")
                        except NoSuchElementException:
                            property_data["broker"] = "No Broker"

                    all_properties.append(property_data)

                except Exception as e:
                    print(f"  Error parsing row: {e}")

            result = driver.execute_cdp_cmd('Page.captureScreenshot', {
                'format': 'png',
                'captureBeyondViewport': True,
            })
            with open(f'screenshot_page_{page_number}.png', 'wb') as f:
                f.write(base64.b64decode(result['data']))
            print(f"  Screenshot saved: screenshot_page_{page_number}.png")

            if page_number < 2:
                next_page = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="listing"]/table/tbody/tr/td/table/tbody/tr[2]/td/table[5]/tbody/tr[1]/td[3]/div/a'))
                )
                next_page.click()

    finally:
        driver.quit()

    df = pd.DataFrame(all_properties)
    df.to_csv('test_output.csv', index=False)
    print(f"\nDone. {len(df)} properties saved to test_output.csv")


def _normalize(s):
    """Lowercase, collapse whitespace, strip."""
    import unicodedata
    s = unicodedata.normalize('NFC', str(s))
    return re.sub(r'\s+', ' ', s).strip().lower()


def _clean_for_validation(row):
    """Return a dict of cleaned field values ready for text-search comparison."""
    # title: strip trailing ellipsis, normalize whitespace
    title = str(row.get('title', '')).strip().rstrip('.').rstrip('\u2026').strip()
    title = re.sub(r'\s+', ' ', title)

    # price: use as-is
    price = str(row.get('price', '')).strip()

    # type: strip leading comma and whitespace
    prop_type = str(row.get('type', '')).strip().lstrip(',').strip()

    # barrio: strip "Urbanizacion-" / "Barrio-" / etc. prefix
    barrio_raw = str(row.get('barrio', '')).strip()
    barrio = barrio_raw.split('-', 1)[1].strip() if '-' in barrio_raw else barrio_raw

    # pueblo: use as-is
    pueblo = str(row.get('pueblo', '')).strip()

    # rooms: use as-is (checked separately with regex)
    rooms = str(row.get('rooms', '')).strip()

    # broker: strip "ClasificadosOnline [barrio-name] de " prefix and license numbers
    broker_raw = str(row.get('broker', '')).strip()
    broker = None  # None = skip this field
    if broker_raw not in ('No Broker', 'Multiple Sellers', '', 'nan'):
        b = broker_raw.replace('ClasificadosOnline', '').strip()
        try:
            barrio_name = re.sub(r'[-]', ' ', barrio_raw.split('-', 1)[1])
            b = re.sub(re.escape(barrio_name), '', b, flags=re.IGNORECASE).strip()
            if b.lower().startswith('de '):
                b = b[3:]
        except Exception:
            pass
        # strip trailing license numbers like "#12345" or "L 12345"
        b = re.sub(r'\s*[#L]\s*\d+\s*$', '', b.strip()).strip()
        broker = b if b else None

    return {
        'title': title,
        'price': price,
        'type': prop_type,
        'barrio': barrio,
        'pueblo': pueblo,
        'rooms': rooms,
        'broker': broker,
    }


def validate_properties():
    df = pd.read_csv('test_output.csv')
    df_page1 = df[df['page'] == 1].copy()
    print(f"Validating {len(df_page1)} page-1 properties against their detail pages...")

    options = Options()
    driver = webdriver.Chrome(options=options)
    results = []

    try:
        for i, (_, row) in enumerate(df_page1.iterrows(), 1):
            print(f"  [{i}/{len(df_page1)}] property {row['propertyid']}...", end=' ', flush=True)
            try:
                driver.get(row['link'])
                WebDriverWait(driver, 15).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                body = driver.find_element(By.TAG_NAME, 'body').text.lower()
            except Exception as e:
                print(f"ERROR loading page: {e}")
                continue

            cleaned = _clean_for_validation(row)
            body_norm = _normalize(body)

            def check(value):
                if value is None:
                    return None
                v = _normalize(value)
                if not v or v == 'nan':
                    return None
                return v in body_norm

            checks = {}
            checks['title_ok']  = check(cleaned['title'])
            checks['price_ok']  = check(cleaned['price'])
            checks['type_ok']   = check(cleaned['type'])
            checks['barrio_ok'] = check(cleaned['barrio'])
            checks['pueblo_ok'] = check(cleaned['pueblo'])
            checks['broker_ok'] = check(cleaned['broker'])

            # rooms: match either listing format ("4 cuartos") or detail format ("cuartos - 4")
            rooms_val = cleaned['rooms']
            if rooms_val and rooms_val.lower() != 'nan':
                bed = re.search(r'(>=?\d+|\d+)\s+cuartos?', rooms_val, re.IGNORECASE)
                bath = re.search(r'(>=?\d+|\d+)\s+ba[ñn]os?', rooms_val, re.IGNORECASE)
                room_results = []
                for match_obj, word in [(bed, 'cuartos?'), (bath, r'ba[ñn]os?')]:
                    if not match_obj:
                        continue
                    num = re.escape(match_obj.group(1))
                    found = bool(
                        re.search(num + r'\s*' + word, body_norm, re.IGNORECASE) or
                        re.search(word + r'[\s\-]+' + num, body_norm, re.IGNORECASE)
                    )
                    room_results.append(found)
                checks['rooms_ok'] = all(room_results) if room_results else None
            else:
                checks['rooms_ok'] = None

            # optioned: only check presence when True
            if row.get('optioned') is True or str(row.get('optioned')).lower() == 'true':
                checks['optioned_ok'] = 'optioned' in body
            else:
                checks['optioned_ok'] = None

            counted = {k: v for k, v in checks.items() if v is not None}
            fields_checked = len(counted)
            fields_matched = sum(1 for v in counted.values() if v)
            match_pct = round(fields_matched / fields_checked * 100, 1) if fields_checked else 0.0

            if match_pct == 100:
                result_label = 'pass'
            elif match_pct >= 80:
                result_label = 'flag'
            else:
                result_label = 'fail'

            print(f"{result_label} ({match_pct}%)")

            results.append({
                'propertyid':     row['propertyid'],
                'title_ok':       checks['title_ok'],
                'price_ok':       checks['price_ok'],
                'type_ok':        checks['type_ok'],
                'barrio_ok':      checks['barrio_ok'],
                'pueblo_ok':      checks['pueblo_ok'],
                'rooms_ok':       checks['rooms_ok'],
                'broker_ok':      checks['broker_ok'],
                'optioned_ok':    checks['optioned_ok'],
                'fields_checked': fields_checked,
                'fields_matched': fields_matched,
                'match_pct':      match_pct,
                'result':         result_label,
            })

    finally:
        driver.quit()

    out = pd.DataFrame(results)
    out.to_csv('test_validation.csv', index=False)

    passes = (out['result'] == 'pass').sum()
    flags  = (out['result'] == 'flag').sum()
    fails  = (out['result'] == 'fail').sum()
    print(f"\nValidation complete: {passes} pass, {flags} flag, {fails} fail (out of {len(out)} properties)")
    print("Results saved to test_validation.csv")


def _clean_sample_for_upload(df_raw):
    """Apply the same cleaning as clean_real_estate_data() to a raw sample DataFrame."""
    df = df_raw.copy()

    df['type'] = df['type'].str.replace(r'^,\s*', '', regex=True).str.strip()

    def clean_broker(broker_name, barrio_name):
        b = str(broker_name).replace("ClasificadosOnline", "").strip()
        try:
            barrio_cleaned = re.sub(r"[-]", " ", str(barrio_name).split("-", 1)[1])
            b = re.sub(re.escape(barrio_cleaned), "", b, flags=re.IGNORECASE).strip()
            if b.lower().startswith("de "):
                b = b[3:]
        except Exception:
            pass
        return b.strip()

    df["broker"] = df.apply(lambda row: clean_broker(row["broker"], row["barrio"]), axis=1)

    df['bedrooms'] = df['rooms'].str.extract(r'(>=\s*\d+|\d+)\s+Cuartos', expand=False).fillna("0")
    df['bathrooms'] = df['rooms'].str.extract(r'(>=\s*\d+|\d+)\s+Baños', expand=False).fillna("0")
    df.drop(columns=['rooms'], inplace=True)

    df['barrio'] = df['barrio'].fillna('').str.strip()
    df['pueblo'] = df['pueblo'].fillna('').str.strip()

    municipios_path = Path(__file__).parent / "PR_Municipios"
    municipio = pd.read_csv(municipios_path)
    df['pueblo_name'] = df['pueblo'].apply(lambda x: next((name for name in municipio['name'] if name in x), None))
    merged = pd.merge(df, municipio, left_on='pueblo_name', right_on='name', how='left')
    df['region'] = merged['region']
    df.drop(columns=['pueblo_name'], inplace=True)

    df['price'] = df['price'].str.replace('$', '', regex=False).str.replace(',', '', regex=False).astype(float)

    df = df.drop_duplicates(subset=['propertyid'], keep='first').reset_index(drop=True)
    df.drop(columns=['page'], inplace=True, errors='ignore')
    df.rename(columns={'propertyid': 'property_id'}, inplace=True)

    return df


def test_upload():
    from dotenv import load_dotenv
    from supabase import create_client

    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    log = {
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "uploaded_records": [],
        "new_ids": [],
        "preexisting_ids": [],
    }

    def step(name, passed, detail=None, error=None):
        entry = {"step": name, "result": "PASS" if passed else "FAIL"}
        if detail:
            entry["detail"] = detail
        if error:
            entry["error"] = str(error)
        log["steps"].append(entry)
        status = "[PASS]" if passed else "[FAIL]"
        msg = f"  {status} {name}"
        if detail:
            msg += f" — {detail}"
        if error:
            msg += f"\n         ERROR: {error}"
        print(msg)
        return passed

    print("\n=== Supabase Upload Test ===\n")
    overall = True

    # Step 1: credentials
    try:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL or SUPABASE_KEY missing from .env")
        sb = create_client(url, key)
        overall &= step("Credentials loaded", True)
    except Exception as e:
        overall &= step("Credentials loaded", False, error=e)
        _write_log(log)
        return

    # Step 2: read scraping_log
    try:
        resp = sb.table("scraping_log").select("date").order("date", desc=True).limit(1).execute()
        last_date = resp.data[0]["date"] if resp.data else "no entries"
        overall &= step("Read scraping_log", True, detail=f"last scrape: {last_date}")
    except Exception as e:
        overall &= step("Read scraping_log", False, error=e)
        overall = False

    # Step 3: prepare sample
    try:
        raw = pd.read_csv(base_dir / "test_output.csv")
        sample_raw = raw[raw['page'] == 1].head(3).copy()
        sample = _clean_sample_for_upload(sample_raw)
        log["uploaded_records"] = sample.to_dict(orient='records')
        overall &= step("Prepare 3-row sample", True, detail=f"property_ids: {sample['property_id'].tolist()}")
    except Exception as e:
        overall &= step("Prepare 3-row sample", False, error=e)
        _write_log(log)
        return

    # Step 4: check what already exists
    try:
        ids = [str(pid) for pid in sample['property_id'].tolist()]
        existing = sb.table("properties").select("property_id").in_("property_id", ids).execute()
        preexisting_ids = [str(r["property_id"]) for r in existing.data]
        new_ids = [pid for pid in ids if pid not in preexisting_ids]
        log["new_ids"] = new_ids
        log["preexisting_ids"] = preexisting_ids
        overall &= step("Check existing records", True,
                        detail=f"{len(new_ids)} new, {len(preexisting_ids)} pre-existing")
    except Exception as e:
        overall &= step("Check existing records", False, error=e)
        overall = False

    # Step 5: insert only new records (same as production — no upsert conflict)
    today_str = datetime.now().date().isoformat()
    try:
        inserts = []
        for _, row in sample.iterrows():
            if str(row["property_id"]) not in new_ids:
                continue
            inserts.append({
                "property_id": str(row["property_id"]),
                "title": row["title"],
                "price": row["price"],
                "price_changed": False,
                "previous_price": None,
                "type": row["type"],
                "barrio": row["barrio"],
                "pueblo": row["pueblo"],
                "link": row["link"],
                "broker": row["broker"],
                "piclink": row["piclink"],
                "bedrooms": row["bedrooms"],
                "bathrooms": row["bathrooms"],
                "region": row.get("region"),
                "optioned": bool(row["optioned"]),
                "first_seen": today_str,
                "last_seen": today_str,
                "times_seen": 1,
            })
        if inserts:
            sb.table("properties").insert(inserts).execute()
            detail = f"{len(inserts)} inserted, {len(preexisting_ids)} pre-existing (skipped)"
        else:
            detail = "all 3 already exist in DB — write path not exercised; try re-running after cleanup"
        overall &= step("Write to properties", True, detail=detail)
    except Exception as e:
        overall &= step("Write to properties", False, error=e)
        overall = False

    # Step 6: verify new inserts are present
    try:
        if new_ids:
            verified = sb.table("properties").select("property_id").in_("property_id", new_ids).execute()
            found_ids = [str(r["property_id"]) for r in verified.data]
            all_found = all(pid in found_ids for pid in new_ids)
            overall &= step("Verify new records in DB", all_found,
                            detail=f"{len(found_ids)}/{len(new_ids)} confirmed")
        else:
            step("Verify new records in DB", True, detail="skipped — no new records were inserted")
    except Exception as e:
        overall &= step("Verify new records in DB", False, error=e)
        overall = False

    # Step 7: cleanup (delete only newly inserted rows)
    if new_ids:
        try:
            sb.table("properties").delete().in_("property_id", new_ids).execute()
            overall &= step("Cleanup new rows", True,
                            detail=f"deleted {len(new_ids)} test row(s)")
        except Exception as e:
            overall &= step("Cleanup new rows", False, error=e)
            overall = False
    else:
        step("Cleanup new rows", True, detail="nothing to delete (all were pre-existing)")

    log_path = _write_log(log)
    result_str = "PASS" if overall else "FAIL"
    print(f"\nOverall: {result_str}  |  Log saved to {log_path}\n")


def _write_log(log):
    log_path = Path(__file__).parent / "test_upload_log.json"
    with open(log_path, 'w') as f:
        json.dump(log, f, indent=2, default=str)
    return log_path


if __name__ == '__main__':
    import sys
    if '--validate' in sys.argv:
        validate_properties()
    elif '--test-upload' in sys.argv:
        test_upload()
    else:
        main()
