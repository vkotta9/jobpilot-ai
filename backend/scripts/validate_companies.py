"""Detect which public job board each company uses (run from the internet, e.g. GitHub Actions).

Usage: python scripts/validate_companies.py <chunk_index> <chunk_count>
Prints one ::notice:: line per company: name=kind:identifier:jobs  (or name=none)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sources.detect import detect  # noqa: E402

CANDIDATES = """Airbnb|Stripe|Databricks|Figma|Notion|Ramp|Brex|Plaid|Robinhood|Coinbase|Discord|Dropbox|Pinterest|Reddit|Lyft|
DoorDash|Instacart|Gusto|Asana|Airtable|Cloudflare|Datadog|MongoDB|Elastic|GitLab|HashiCorp|Twilio|Okta|Samsara|Palantir|
Spotify|Anthropic|OpenAI|Scale AI|Duolingo|Roblox|Affirm|Chime|SoFi|NerdWallet|Squarespace|Etsy|Peloton|Carta|Rippling|
Deel|Mercury|Retool|Vercel|Supabase|Linear|Perplexity|Cohere|Hugging Face|Anduril|Flexport|Toast|Wealthfront|Benchling|
Verkada|Faire|Grammarly|Atlassian|PostHog|Zapier|Snowflake|Confluent|Snyk|Postman|Miro|Canva|Webflow|Calendly|Intercom|
Klaviyo|HubSpot|Lattice|Gong|Navan|Chainalysis|Kraken|Gemini|Nuro|Aurora|Zoox|Waymo|Cruise|Scale|Weights & Biases|
Replit|Cursor|Glean|Harvey|Runway|ElevenLabs|Mistral|Together AI|Modal|Pinecone|Weaviate|Grafana Labs|Fivetran|dbt Labs|
Airbyte|Starburst|ClickHouse|Cockroach Labs|PlanetScale|Neon|Temporal|Sourcegraph|Vanta|Drata|1Password|Tailscale|
Zscaler|CrowdStrike|SentinelOne|Wiz|Abnormal Security|Arctic Wolf|Twitch|Quora|Yelp|Zillow|Redfin|Opendoor|Compass|
Wayfair|Chewy|Grubhub|Poshmark|ThredUp|StockX|Shopify|Square|Block|Nextdoor|Bumble|Hinge|Match Group|Tinder|
Epic Games|Riot Games|Unity|Niantic|Discord|Mozilla|Wikimedia|Khan Academy|Coursera|Udemy|Chegg|Quizlet|
Oscar Health|Ro|Hims & Hers|Headway|Spring Health|Lyra Health|Cityblock|Devoted Health|Tempus|Flatiron Health""".replace("\n", "")

def main() -> int:
    names = list(dict.fromkeys(n.strip() for n in CANDIDATES.split("|") if n.strip()))
    i, k = int(sys.argv[1]), int(sys.argv[2])
    chunk = names[i::k]
    rows = []
    for n in chunk:
        d = detect(n)
        rows.append(f"{n}={d.kind}:{d.identifier}:{d.jobs}" if d.status == "found" else f"{n}=none")
    # GitHub keeps a limited number of annotations per step, so pack results into a few lines
    for j in range(0, len(rows), 12):
        print("::notice title=companies::" + " | ".join(rows[j:j + 12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
