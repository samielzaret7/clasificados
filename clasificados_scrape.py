import csv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
import re
import numpy as np
from random import randint
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
import os




#options = Options() 
#driver = webdriver.Chrome(options=options)
#driver.get('https://www.clasificadosonline.com/RealEstate.asp')


def format_duration(seconds):
    """Convert seconds to HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def log_scraping_results(total_properties, scraped, updated, uploaded, error_rows, batches_skipped,
                         scrape_start, scrape_end, upload_start, upload_end):

    # Compute time durations
    scrape_time = format_duration((scrape_end - scrape_start).total_seconds())
    upload_time = format_duration((upload_end - upload_start).total_seconds())
    total_time = format_duration((upload_end - scrape_start).total_seconds())

    # Format timestamps
    scrape_start_str = scrape_start.strftime("%H:%M:%S")
    scrape_end_str = scrape_end.strftime("%H:%M:%S")
    upload_start_str = upload_start.strftime("%H:%M:%S")
    upload_end_str = upload_end.strftime("%H:%M:%S")

    # Prepare data for Supabase
    log_data = {
        "date": datetime.now().date().strftime("%Y-%m-%d"),
        "scrape_start": scrape_start_str,
        "scrape_end": scrape_end_str,
        "scrape_time": scrape_time,  # Now stored as HH:MM:SS
        "upload_start": upload_start_str,
        "upload_end": upload_end_str,
        "upload_time": upload_time,
        "total_time": total_time,
        "total_properties": total_properties,
        "scraped": scraped,
        "error_rows": error_rows,
        "updated": updated,
        "uploaded": uploaded,
        "batches_skipped": batches_skipped
    }

    # Insert log into Supabase
    try:
        response = supabase.table("scraping_log").insert(log_data).execute()
        print(f"✅ Scraping log uploaded successfully: {response}")
    except Exception as e:
        print(f"❌ Error uploading scraping log: {e}")



scrape_start = datetime.now()  # Start time for scraping
print(f"⏳ Scrape started at {scrape_start.strftime('%H:%M:%S')}")


from selenium.webdriver.chrome.service import Service


chrome_driver_url = "http://127.0.0.1:9515"  # Connect to running WebDriver

# Chrome options
options = Options()


try:
    # Try to connect to an existing ChromeDriver session
    driver = webdriver.Remote(command_executor=chrome_driver_url, options=options)
    print("✅ Connected to existing WebDriver session!")
except Exception as e:
    print("❌ No existing WebDriver found, starting a new session...")

    # Start a new ChromeDriver session (Correct way in Selenium 4)
    service = Service("/Users/zenmaster/Programming/clasificados/chromedriver-mac-x64/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

driver.get('https://www.clasificadosonline.com/RealEstate.asp')





time.sleep(10)
ver_listado = driver.find_element(By.XPATH,'//*[@id="BtnSearchListing"]')
ver_listado.click()

order_by = driver.find_element(By.XPATH,'//*[@id="jumpMenu"]')

order_by = driver.find_element(By.XPATH,'//*[@id="jumpMenu"]')
order_by.click()
ultimos_publicados = driver.find_element(By.XPATH,'//*[@id="jumpMenu"]/option[7]')
ultimos_publicados.click()


total_properties = driver.find_element(By.XPATH,'//*[@id="listing"]/table/tbody/tr/td/table/tbody/tr[2]/td/table[4]/tbody/tr/td[2]/div[2]/span').text[-4:]

def clean_real_estate_data(df):
    # Clean the 'Type' column by removing leading commas and whitespace
    df['type'] = df['type'].str.replace(r'^,\s*', '', regex=True).str.strip()
    
    # Clean the 'Broker' column using the combined logic
    def clean_broker(broker_name, barrio_name):
        try:

            # Remove the "ClasificadosOnline" text from the broker name
            broker_name = broker_name.replace("ClasificadosOnline", "").strip()

            # Extract the barrio name (e.g., "Las Mansiones de Villa Rica")
            barrio_cleaned = re.sub(r"[-]", " ", barrio_name.split("-", 1)[1])  # Clean barrio name

            # Remove the barrio part from the broker column
            broker_name_cleaned = re.sub(re.escape(barrio_cleaned), "", broker_name, flags=re.IGNORECASE)

            # Strip leading/trailing whitespace and "de" artifacts
            broker_name_cleaned = broker_name_cleaned.strip()
            if broker_name_cleaned.lower().startswith("de "):
                broker_name_cleaned = broker_name_cleaned[3:]  # Remove leading "de"

        except Exception as e:
            print(f"An error occurred: {e}")
    
        # Return the cleaned broker name
        return broker_name_cleaned.strip()
    
    # Apply the clean_broker function to the 'Broker' column and remove the "ClasificadosOnline" text
    df["broker"] = df.apply(lambda row: clean_broker(row["broker"], row["barrio"]), axis=1)
    

    # Extract the number of bedrooms and bathrooms from the 'Rooms' column
    # Extract bedrooms (including cases with >=)
    df['bedrooms'] = df['rooms'].str.extract(r'(>=\s*\d+|\d+)\s+Cuartos', expand=False)

    # Extract bathrooms
    df['bathrooms'] = df['rooms'].str.extract(r'(>=\s*\d+|\d+)\s+Baños', expand=False)

    # Fill NaN values with string 0
    df[['bedrooms', 'bathrooms']] = df[['bedrooms', 'bathrooms']].fillna("0")


    # Drop the Rooms column
    df.drop(columns=['rooms'], inplace=True)

    # Fill missing values in the 'barrio' and 'pueblo' columns with empty strings
    df['barrio'] = df['barrio'].fillna('')
    df['pueblo'] = df['pueblo'].fillna('')

    # Strip any leading or trailing whitespace from the 'barrio' and 'pueblo' columns
    df['barrio'] = df['barrio'].str.strip()
    df['pueblo'] = df['pueblo'].str.strip()

    # Load the municipio data from the CSV file
    municipio = pd.read_csv('/Users/zenmaster/Programming/clasificados/PR_Municipios')

    # Check if the word from the name column in municipio is present in the pueblo column within data
    df['pueblo_name'] = df['pueblo'].apply(lambda x: next((name for name in municipio['name'] if name in x), None))

    # Merge the dataframes on the extracted pueblo names and the name column
    merged_df = pd.merge(df, municipio, left_on='pueblo_name', right_on='name', how='left')

    # Add the region column to the original data dataframe
    df['region'] = merged_df['region']

    # Drop the temporary pueblo_name column
    df.drop(columns=['pueblo_name'], inplace=True)

    # Clean the 'price' column by removing the dollar sign and commas and converting it to a float
    df['price'] = df['price'].str.replace('$','').str.replace(',','').astype(float)

    # Remove duplicate rows based on the 'PropertyID' column
    # Keep the first occurrence and log the duplicates
    duplicates = df[df.duplicated(subset=['propertyid'], keep=False)]
    
    if not duplicates.empty:
        num_duplicates = duplicates['propertyid'].nunique()  # Count unique duplicate property IDs
        print(f"Duplicate Properties Found: {num_duplicates}")
        print(duplicates.to_string(index=False))

    else:
        print("No duplicate properties found")

    # Drop duplicates and keep the first occurrence
    df = df.drop_duplicates(subset=['propertyid'], keep='first').reset_index(drop=True)

    return df



# Function to extract property ID from link
def extract_property_id(link):
    match = re.search(r"ID=(\d+)", link)
    return match.group(1) if match else None

# Track seen property IDs to skip duplicates
seen_properties = set()
all_properties = []
page_number = 1
error_rows = 0

# Start scraping pages
while True:
    print(f"Scraping page {page_number}...")

    # Ensure sorting is set to "Latest Published"
    dropdown_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, '//*[@id="jumpMenu"]')))
    select = Select(dropdown_element)
    
    if select.first_selected_option.text != 'Ultimos Publicados (Más Recientes Primeros)':
        dropdown_element.click()
        time.sleep(2)
        latest_option = driver.find_element(By.XPATH, '//*[@id="jumpMenu"]/option[7]')
        latest_option.click()
        time.sleep(7)

    # Extract property rows
    property_rows = driver.find_elements(By.CSS_SELECTOR, "#listing table tbody tr td table tbody tr:nth-child(2) td div.dv-classified-row.dv-classified-row-v2")

    for row in property_rows:
        try:
            link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) table tbody tr:nth-child(1) > td > a")
            link = link_element.get_attribute("href")
            property_id = extract_property_id(link)

            if property_id in seen_properties:
                continue  # Skip duplicate properties
            
            seen_properties.add(property_id)

            # Extract data from row
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
                "optioned": False  # Default value
            }

            # Extract additional type if available
            try:
                type_2 = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(5)").text
                property_data["type"] += f" {type_2}"
            except:
                pass  # No second type available

            # Check if property is "Optioned"
            try:
                optioned_text = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(1) > div:nth-child(2) > span:nth-child(6)").text
                if "Optioned" in optioned_text:
                    property_data["optioned"] = True
            except:
                pass  # No optioned text found

            # Extract broker information
            if "MultipleSellers" in property_data["link"]:
                property_data["broker"] = "Multiple Sellers"
            else:
                try:
                    property_data["broker"] = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > table > tbody > tr:nth-child(2) > td:nth-child(2) > center > a > img").get_attribute("alt")
                except:
                    property_data["broker"] = "No Broker"

            all_properties.append(property_data)

        except Exception as e:
            error_rows += 1

    # Click "Next Page" if available
    try:
        next_page = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="listing"]/table/tbody/tr/td/table/tbody/tr[2]/td/table[5]/tbody/tr[1]/td[3]/div/a')))
        next_page.click()
        page_number += 1
    except:
        print("No more pages available.")
        break  # Stop scraping

# Convert to DataFrame
df = pd.DataFrame(all_properties)
print(f"✅ Scraped {len(df)} properties successfully.")
print(f"❌ {error_rows} rows weren't extracted due to missing data or other error.")

scraped = len(df)

cleaned_df = clean_real_estate_data(df)

cleaned_df.to_csv("classifieds_data.csv", index=False)

scrape_end = datetime.now()  # End time for scraping
print(f"✅ Scrape finished at {scrape_end.strftime('%H:%M:%S')}")


upload_start = datetime.now()  # Start time for uploading
print(f"⏳ Upload started at {upload_start.strftime('%H:%M:%S')}")

# Load environment Variable
load_dotenv("/Users/zenmaster/Programming/clasificados/.env")

# Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL") 
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# Function to upload properties to the database
def upload_properties_to_database(df, batch_size=500, max_retries=5):

    # Fetch the last scrape date from srcaping_log table
    while retry_attempts < max_retries:
        try:
            response = supabase.table("scraping_log").select("date").order("date", desc=True).limit(1).execute()

            if response.data:
                last_scrape_date = datetime.strptime(response.data[0]["date"], "%Y-%m-%d").date()
                break

        except Exception as e:
            retry_attempts += 1
            wait_time = randint(1, 2 ** retry_attempts)
            print(f"Retry {retry_attempts}/{max_retries} for fetching last scrape date due to error: {e}")
            time.sleep(wait_time)


    today = datetime.now().date()

    # Calculate days since last scrape
    days_since_last_scrape = (today - last_scrape_date).days

    today = str(today) # Convert date to string for database

    # Reset rety_attempts
    retry_attempts = 0
    properties_updated = 0
    properties_uploaded = 0
    batches_skipped = 0  # Track how many batches were skipped

    skipped_batches = []  # Store skipped batches for manual processing

    # Process the DataFrame in batches
    for batch_index, batch in enumerate(np.array_split(df, len(df) // batch_size + 1)):
        retry_attempts = 0

        while retry_attempts < max_retries:
            try:
                print(f"Processing batch {batch_index + 1}/{len(df) // batch_size + 1}")

                # Fetch existing properties in batch
                property_ids = batch["propertyid"].tolist()
                existing_properties = supabase.table("properties").select("*").in_("property_id", property_ids).execute()

                existing_data = {prop["property_id"]: prop for prop in existing_properties.data}

                updates = []
                inserts = []

                for _, property in batch.iterrows():
                    property_id = property["propertyid"]

                    if property_id in existing_data:
                        db_property = existing_data[property_id]

                        # Skip properties already seen today
                        if db_property["last_seen"] == today:
                            continue

                        # Prepare update data
                        update_data = {
                            "last_seen": today,
                            "times_seen": db_property["times_seen"] + days_since_last_scrape
                        }

                        # Check for price changes
                        db_price = db_property["price"]
                        scraped_price = property["price"]
                        if db_price != scraped_price:
                            update_data["price_changed"] = True
                            update_data["previous_price"] = db_price
                            update_data["price"] = scraped_price

                        # Check for optioned status changes
                        db_optioned = db_property["optioned"]
                        scraped_optioned = property["optioned"]
                        if db_optioned != scraped_optioned:
                            update_data["optioned"] = scraped_optioned

                        updates.append({"property_id": property_id, **update_data})

                    else:
                        # Prepare new property insert data
                        inserts.append({
                            "property_id": property_id,
                            "title": property["title"],
                            "price": property["price"],
                            "price_changed": False,
                            "previous_price": None,
                            "type": property["type"],
                            "barrio": property["barrio"],
                            "pueblo": property["pueblo"],
                            "link": property["link"],
                            "broker": property["broker"],
                            "piclink": property["piclink"],
                            "bedrooms": property["bedrooms"],
                            "bathrooms": property["bathrooms"],
                            "region": property["region"],
                            "optioned": property["optioned"],
                            "first_seen": today,
                            "last_seen": today,
                            "times_seen": 1
                        })

                # Perform batch updates
                if updates:
                    for update_data in updates:
                        property_id = update_data["property_id"]  # Extract property_id for filtering
                        response = supabase.table("properties").update(update_data).eq("property_id", property_id).execute()
                        if response.data:  # ✅ Only count if update was successful
                            properties_updated += 1
                
                # Perform batch inserts
                if inserts:
                    #print("Inserting properties:", inserts[:3])
                    response = supabase.table("properties").insert(inserts).execute()
                    if response.data:  # ✅ Only count if insert was successful
                        properties_uploaded += len(response.data)

                # Break out of retry loop if successful
                break

            except Exception as e:
                # Retry logic with exponential backoff
                retry_attempts += 1
                wait_time = randint(1, 2 ** retry_attempts)
                print(f"Retry {retry_attempts}/{max_retries} for batch {batch_index + 1} due to error: {e}")
                time.sleep(wait_time)
                

        else:
            # If max retries exceeded, log the skipped batch
            print(f"Skipping batch {batch_index + 1} after {max_retries} failed attempts.")
            batches_skipped += 1
            skipped_batches.append(batch)

    # Save skipped batches to a CSV file for manual processing
    if skipped_batches:
        skipped_df = pd.concat(skipped_batches)
        skipped_df.to_csv(f"skipped_batches_{today}.csv", index=False)
        print(f"Saved {batches_skipped} skipped batches to skipped_batches_{today}.csv for manual processing.")

    print(f"✅ Properties Updated: {properties_updated}")
    print(f"✅ Properties Uploaded: {properties_uploaded}")
    print(f"❌ Batches Skipped: {batches_skipped}")

    return properties_updated, properties_uploaded, batches_skipped

properties_updated, properties_uploaded, batches_skipped = upload_properties_to_database(cleaned_df, batch_size=500, max_retries=5)


upload_end = datetime.now()  # End time for uploading
print(f"✅ Upload finished at {upload_end.strftime('%H:%M:%S')}")


log_scraping_results(total_properties, scraped, properties_updated, properties_uploaded, error_rows, batches_skipped,
                         scrape_start, scrape_end, upload_start, upload_end)
