import os
import json
import time
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import anthropic
from supabase import create_client

load_dotenv()

# Path to the input data and the cache file that tracks what's already been processed
DATA_PATH = "./full_plant_diseases.json"
CACHE_PATH = "./cache.json"

# How long to wait between requests (seconds) to avoid hitting rate limits
DELAY_SECONDS = 2

# Max characters to pull from each article (keeps prompts from getting too large)
MAX_ARTICLE_LENGTH = 4000

# Set up logging to write to both the console and a timestamped log file.
# Each run creates a new file under ./logs/ so you have a full history.
os.makedirs("./logs", exist_ok=True)
log_filename = f"./logs/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# Set up the Anthropic and Supabase clients using keys from .env
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"],
)


def extract_article_text(url):
    """Download a webpage and return the plain text from all paragraph tags,
    capped at MAX_ARTICLE_LENGTH characters."""
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        text = "\n".join(p.get_text() for p in soup.find_all("p"))
        return text[:MAX_ARTICLE_LENGTH]
    except Exception as e:
        log.warning(f"Could not fetch article ({e}): {url}")
        return ""


def generate_care(genus, disease, plant_list, content):
    """Send the article content to Claude and ask it to write a care guide."""
    prompt = f"""You are a plant care expert.

Generate a practical care or treatment guide for plant disease identification app users.

Genus: {genus}
Condition: {disease}
Affected Plants: {", ".join(plant_list)}

Include:
- Symptoms
- Causes
- Treatment steps
- Prevention tips

Keep it concise (200-400 words). Write in plain language suitable for home gardeners.

Reference Material:
{content}"""

    message = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


def build_disease_map(data):
    """Go through the raw JSON and build a dict of unique genus+disease pairs.
    This avoids generating the same care text twice when multiple plants
    in the same genus share the same disease and articles."""
    disease_map = {}

    for genus_obj in data:
        genus = genus_obj["genus"]
        plants = genus_obj["plants"]
        diseases = genus_obj["diseases"]

        for disease_obj in diseases:
            key = f"{genus}::{disease_obj['name']}"

            if key not in disease_map:
                disease_map[key] = {
                    "genus": genus,
                    "disease_name": disease_obj["name"],
                    "plants": list(plants),
                    "articles": list(disease_obj["articles"]),
                }
            else:
                # If the key already exists, add any new plant names to the list
                for plant in plants:
                    if plant not in disease_map[key]["plants"]:
                        disease_map[key]["plants"].append(plant)

    return disease_map


def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    # Load the cache so we can skip anything already processed
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)
    else:
        cache = {}

    disease_map = build_disease_map(data)
    total = len(disease_map)
    processed = 0

    log.info(f"Log file: {log_filename}")
    log.info(f"Found {total} unique genus+disease pairs to process.")

    for cache_key, entry in disease_map.items():
        genus = entry["genus"]
        disease_name = entry["disease_name"]
        plants = entry["plants"]
        articles = entry["articles"]

        if cache_key in cache:
            log.info(f"Skipping (already done): {cache_key}")
            continue

        processed += 1
        log.info(f"[{processed}/{total}] Processing: {cache_key}")

        # Fetch and combine text from all reference articles
        combined_text = ""
        for url in articles:
            text = extract_article_text(url)
            if text:
                log.info(f"  Fetched {len(text)} chars from {url}")
            combined_text += text + "\n\n"
            time.sleep(0.3)

        if not combined_text.strip():
            log.warning(f"  No article content found for {cache_key}, skipping.")
            continue

        # Generate the care text using Claude
        try:
            disease_label = "Healthy plant care" if disease_name == "Healthy" else disease_name
            care_text = generate_care(genus, disease_label, plants, combined_text)
            log.info(f"  Generated {len(care_text)} chars of care text.")
        except Exception as e:
            log.error(f"  AI generation failed: {e}")
            continue

        # Write the result to the disease_static table in Supabase
        result = (
            supabase.table("disease_static")
            .update({"recommended_action": care_text})
            .eq("disease_name", disease_name)
            .execute()
        )

        if hasattr(result, "error") and result.error:
            log.error(f"  Database update failed: {result.error}")
            continue

        # Mark this pair as done in the cache file
        cache[cache_key] = True
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)

        log.info(f"  Saved: {cache_key}")

        time.sleep(DELAY_SECONDS)

    log.info("All done.")


if __name__ == "__main__":
    main()