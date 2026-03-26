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
DATA_PATH = "./dry_run.json"  # CHANGE TO NAME OF JSON WITH ALL PLANTS TO RUN
CACHE_PATH = "./cache.json"

# How long to wait between requests (seconds) to avoid hitting rate limits
DELAY_SECONDS = 1.2

# Max characters to pull from each article (keeps prompts from getting too large)
MAX_ARTICLE_LENGTH = 5000

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


def generate_care(genus, disease, plant_list, content, use_web_search=False):
    """Send the article content to Claude and ask it to write a care guide."""
    prompt = f"""You are a plant care expert.

Generate a care or treatment guide for plant disease identification app users.

Genus: {genus}
Condition: {disease}
Affected Plants: {", ".join(plant_list)}

You must respond with a single valid JSON object using exactly
this structure, with no extra text, markdown, or code fences:

{{
  "disease_name": "{disease}",
  "scientific_name": "the scientific name of the disease",
  "affected_plants": ["plant1", "plant2"],
  "symptoms": [
    {{
      "description": "what the symptom looks like",
      "progression": "how it develops over time"
    }}
  ],
  "onset_period": "time of year or conditions when disease typically appears",
  "causes": [
    {{
      "factor": "name of the cause",
      "detail": "explanation of how this factor contributes"
    }}
  ],
  "treatments": [
    {{
      "step": 1,
      "action": "what to do",
      "detail": "how and why to do it",
      "urgency": "immediate | ongoing | conditional"
    }}
  ],
  "prevention": [
    {{
      "tip": "short tip title",
      "detail": "explanation of the prevention measure"
    }}
  ]
}}

Include 2-3 items in symptoms, causes, treatments, and
prevention. Write in plain language suitable for home gardeners.

Reference Material:
{content}"""

    if use_web_search:
        message = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
        )
    else:
        message = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

    # Claude can return multiple content blocks (e.g. thinking blocks alongside text).
    # Find the first TextBlock explicitly rather than assuming index 0 is always text.
    text_block = next(
        (block for block in message.content if block.type == "text"), None
    )

    if not text_block:
        raise ValueError("No text block found in Claude response.")

    raw = text_block.text.strip()

    # Claude sometimes wraps JSON in markdown code fences despite being told not to.
    # Strip them before parsing so we always get clean JSON.
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    # Validate that the response is proper JSON before returning it.
    # This will raise an error (caught in main) if Claude returns malformed output.
    json.loads(raw)

    return raw


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

        # If articles failed to load, fall back to Claude's web search tool
        # so the entry still gets generated rather than skipped entirely.
        if not combined_text.strip():
            log.warning(
                "  No article content found for "
                f"{cache_key}, falling back to web search."
            )
            combined_text = ""
            use_web_search = True
        else:
            use_web_search = False

        # Generate the care text using Claude
        try:
            disease_label = (
                "Healthy plant care" if disease_name == "Healthy" else disease_name
            )
            care_text = generate_care(
                genus, disease_label, plants, combined_text, use_web_search
            )
            if not care_text:
                log.warning(
                    f"  Claude returned empty response for {cache_key}, skipping."
                )
                continue
            log.info(f"  Generated {len(care_text)} chars of care text.")
        except Exception as e:
            log.error(f"  AI generation failed: {e}")
            continue

        # Write the result to the disease_static table in Supabase.
        # upsert will update the row if disease_name already exists, or insert
        # a new row if it doesn't — so the table can start completely empty.
        # on_conflict tells Supabase which column to match on for the update.
        try:
            result = (
                supabase.table("disease_static")
                .upsert(
                    {
                        "disease_name": disease_name,
                        "genus": genus,
                        "recommended_actions": care_text,
                    },
                    on_conflict="disease_name",
                )
                .execute()
            )
            if not result.data:
                log.warning(
                    "  Upsert returned no data for "
                    f"'{disease_name}', check table permissions."
                )
                continue
        except Exception as e:
            log.error(f"  Database upsert failed: {e}")
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
