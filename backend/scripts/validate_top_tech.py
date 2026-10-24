"""Find the best job feed for each top tech company (run from the internet, e.g. GitHub Actions).

Usage: python scripts/validate_top_tech.py <chunk_index> <chunk_count>
Prints ::notice:: lines: Company=kind:identifier:jobs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sources.detect import detect  # noqa: E402

COMPANIES = [
    # big tech
    "Apple", "Microsoft", "Google", "Amazon", "Meta", "NVIDIA", "Tesla", "Netflix", "Oracle", "Salesforce", "Adobe", "IBM",
    "Intel", "AMD", "Qualcomm", "Cisco", "Broadcom", "Texas Instruments", "Micron", "Applied Materials", "Lam Research", "KLA",
    "Analog Devices", "Marvell", "Arm", "ServiceNow", "Intuit", "Workday", "Snowflake", "Databricks", "Palantir", "Uber",
    "Airbnb", "DoorDash", "Lyft", "Instacart", "Stripe", "PayPal", "Block", "Coinbase", "Robinhood", "Visa", "Mastercard",
    "American Express", "Capital One", "JPMorgan Chase", "Goldman Sachs", "Morgan Stanley", "Bloomberg", "Two Sigma", "Citadel",
    "Jane Street", "Shopify", "Atlassian", "Spotify", "Pinterest", "Snap", "Reddit", "Discord", "Dropbox", "Box", "DocuSign",
    "Zoom", "Twilio", "Okta", "Cloudflare", "Datadog", "MongoDB", "Elastic", "Confluent", "GitLab", "GitHub", "Palo Alto Networks",
    "CrowdStrike", "Fortinet", "Zscaler", "SentinelOne", "Akamai", "Red Hat", "Dell", "HP", "Hewlett Packard Enterprise",
    "Western Digital", "Seagate", "Samsung", "Sony", "LinkedIn", "TikTok", "ByteDance", "Expedia", "Booking", "eBay", "Etsy",
    "Wayfair", "Zillow", "Electronic Arts", "Activision Blizzard", "Roblox", "Epic Games", "Unity", "OpenAI", "Anthropic",
    "Scale AI", "Cohere", "Perplexity", "Hugging Face", "xAI", "Mistral AI", "Waymo", "Aurora", "Rivian", "Lucid Motors",
    "SpaceX", "Anduril", "Lockheed Martin", "Northrop Grumman", "Comcast", "Verizon", "T-Mobile", "Accenture", "Deloitte",
    "Autodesk", "ADP", "Fiserv", "Walmart", "Target", "Disney", "Boeing", "Splunk", "VMware", "Synopsys", "Cadence",
    "Motorola Solutions", "Garmin", "Lenovo", "Siemens", "Bosch", "Philips", "General Motors", "Ford", "Toyota Research Institute",
]


def main() -> int:
    i, k = int(sys.argv[1]), int(sys.argv[2])
    rows = []
    for name in COMPANIES[i::k]:
        d = detect(name)
        rows.append(f"{name}={d.kind}:{d.identifier}:{d.jobs}" if d.status == "found" else f"{name}={d.status}")
    for j in range(0, len(rows), 10):
        print("::notice title=toptech::" + " || ".join(rows[j:j + 10]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
