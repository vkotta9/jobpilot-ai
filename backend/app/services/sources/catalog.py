"""Popular companies with a verified public job board.

Verified from GitHub Actions with scripts/validate_companies.py (Oct 2026): each
board returned open roles. Re-run that workflow to refresh the list.
"""

_RAW = """
Large companies (Workday)|NVIDIA|workday|nvidia|wd5|NVIDIAExternalCareerSite
Large companies (Workday)|Salesforce|workday|salesforce|wd12|External_Career_Site
Large companies (Workday)|Intel|workday|intel|wd1|External
Large companies (Workday)|Adobe|workday|adobe|wd5|external_experienced
Large companies (Workday)|HP|workday|hp|wd5|ExternalCareerSite
Large companies (Workday)|PayPal|workday|paypal|wd1|jobs
Large companies (Workday)|Capital One|workday|capitalone|wd12|Capital_One
Large companies (Workday)|Mastercard|workday|mastercard|wd1|CorporateCareers
Large companies (Workday)|Boeing|workday|boeing|wd1|EXTERNAL_CAREERS
Large companies (Workday)|Target|workday|target|wd5|targetcareers
Large companies (Workday)|Disney|workday|disney|wd5|disneycareer
Large companies (Workday)|Workday|workday|workday|wd5|Workday
Large companies (Workday)|Snap|workday|snapchat|wd1|snap
Large companies (Workday)|Autodesk|workday|autodesk|wd1|Ext
AI & ML|Anthropic|greenhouse|anthropic
AI & ML|OpenAI|ashby|openai
AI & ML|Scale AI|greenhouse|scaleai
AI & ML|Cohere|ashby|cohere
AI & ML|Perplexity|ashby|perplexity
AI & ML|Hugging Face|workable|huggingface
AI & ML|ElevenLabs|ashby|elevenlabs
AI & ML|Harvey|ashby|harvey
AI & ML|Cursor|ashby|cursor
AI & ML|Replit|ashby|replit
AI & ML|Modal|ashby|modal
AI & ML|Pinecone|ashby|pinecone
AI & ML|Runway|ashby|runway
AI & ML|Databricks|greenhouse|databricks
AI & ML|Snowflake|ashby|snowflake
Developer tools & cloud|Cloudflare|greenhouse|cloudflare
Developer tools & cloud|Datadog|greenhouse|datadog
Developer tools & cloud|MongoDB|greenhouse|mongodb
Developer tools & cloud|Elastic|greenhouse|elastic
Developer tools & cloud|GitLab|greenhouse|gitlab
Developer tools & cloud|Vercel|greenhouse|vercel
Developer tools & cloud|Supabase|ashby|supabase
Developer tools & cloud|Linear|ashby|linear
Developer tools & cloud|PostHog|ashby|posthog
Developer tools & cloud|Grafana Labs|greenhouse|grafanalabs
Developer tools & cloud|Fivetran|greenhouse|fivetran
Developer tools & cloud|ClickHouse|ashby|clickhouse
Developer tools & cloud|Cockroach Labs|greenhouse|cockroachlabs
Developer tools & cloud|PlanetScale|greenhouse|planetscale
Developer tools & cloud|Temporal|ashby|temporal
Developer tools & cloud|Starburst|greenhouse|starburst
Developer tools & cloud|Airbyte|ashby|airbyte
Developer tools & cloud|Twilio|greenhouse|twilio
Developer tools & cloud|Tailscale|greenhouse|tailscale
Developer tools & cloud|Zapier|ashby|zapier
Developer tools & cloud|Webflow|ashby|webflow
Productivity & SaaS|Figma|greenhouse|figma
Productivity & SaaS|Notion|ashby|notion
Productivity & SaaS|Asana|greenhouse|asana
Productivity & SaaS|Airtable|greenhouse|airtable
Productivity & SaaS|Dropbox|greenhouse|dropbox
Productivity & SaaS|Miro|ashby|miro
Productivity & SaaS|Canva|smartrecruiters|Canva
Productivity & SaaS|Calendly|greenhouse|calendly
Productivity & SaaS|Intercom|greenhouse|intercom
Productivity & SaaS|Klaviyo|greenhouse|klaviyo
Productivity & SaaS|Samsara|greenhouse|samsara
Productivity & SaaS|Verkada|greenhouse|verkada
Productivity & SaaS|Toast|greenhouse|toast
Productivity & SaaS|Gusto|greenhouse|gusto
Productivity & SaaS|Lattice|greenhouse|lattice
Productivity & SaaS|Squarespace|greenhouse|squarespace
Productivity & SaaS|Palantir|lever|palantir
Fintech & crypto|Stripe|greenhouse|stripe
Fintech & crypto|Plaid|ashby|plaid
Fintech & crypto|Brex|greenhouse|brex
Fintech & crypto|Mercury|greenhouse|mercury
Fintech & crypto|Block|greenhouse|block
Fintech & crypto|Robinhood|greenhouse|robinhood
Fintech & crypto|Coinbase|greenhouse|coinbase
Fintech & crypto|Affirm|greenhouse|affirm
Fintech & crypto|Chime|greenhouse|chime
Fintech & crypto|SoFi|greenhouse|sofi
Fintech & crypto|Carta|greenhouse|carta
Fintech & crypto|NerdWallet|ashby|nerdwallet
Fintech & crypto|Wealthfront|lever|wealthfront
Fintech & crypto|Gemini|greenhouse|gemini
Security|1Password|ashby|1password
Security|Okta|greenhouse|okta
Security|Zscaler|greenhouse|zscaler
Security|Abnormal Security|greenhouse|abnormalsecurity
Security|Vanta|ashby|vanta
Security|Drata|ashby|drata
Security|Snyk|ashby|snyk
Consumer & marketplaces|Airbnb|greenhouse|airbnb
Consumer & marketplaces|Instacart|greenhouse|instacart
Consumer & marketplaces|Lyft|greenhouse|lyft
Consumer & marketplaces|Pinterest|greenhouse|pinterest
Consumer & marketplaces|Reddit|greenhouse|reddit
Consumer & marketplaces|Discord|greenhouse|discord
Consumer & marketplaces|Spotify|lever|spotify
Consumer & marketplaces|Duolingo|greenhouse|duolingo
Consumer & marketplaces|Faire|greenhouse|faire
Consumer & marketplaces|Flexport|greenhouse|flexport
Consumer & marketplaces|Nextdoor|greenhouse|nextdoor
Consumer & marketplaces|Peloton|greenhouse|peloton
Consumer & marketplaces|StockX|greenhouse|stockx
Consumer & marketplaces|Poshmark|ashby|poshmark
Consumer & marketplaces|Quora|ashby|quora
Consumer & marketplaces|Match Group|lever|matchgroup
Gaming & media|Roblox|greenhouse|roblox
Gaming & media|Epic Games|greenhouse|epicgames
Gaming & media|Riot Games|greenhouse|riotgames
Gaming & media|Twitch|greenhouse|twitch
Gaming & media|Mozilla|greenhouse|mozilla
Gaming & media|Wikimedia|greenhouse|wikimedia
Mobility & autonomy|Waymo|greenhouse|waymo
Mobility & autonomy|Zoox|lever|zoox
Mobility & autonomy|Nuro|greenhouse|nuro
Health & education|Oscar Health|greenhouse|oscar
Health & education|Benchling|ashby|benchling
Health & education|Headway|ashby|headway
Health & education|Lyra Health|lever|lyrahealth
Health & education|Ro|lever|ro
Health & education|Flatiron Health|greenhouse|flatironhealth
Health & education|Coursera|greenhouse|coursera
Health & education|Khan Academy|greenhouse|khanacademy
"""

POPULAR: list[dict] = [
    {"category": c, "company": n, "kind": k, "identifier": i}
    for c, n, k, i in (line.split("|", 3) for line in _RAW.strip().splitlines())
]
