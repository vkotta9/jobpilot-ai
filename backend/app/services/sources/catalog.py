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


# Top 100 tech companies (software, AI, cloud, chips, internet). Direct feeds were verified from
# GitHub Actions with scripts/validate_top_tech.py and scripts/live_check.py (Oct 2026). Companies
# without a public feed we can use (Meta, Tesla, Uber, …) are followed through Google Jobs (JSearch).
_TOP = """
Big tech|Apple|apple|apple
Big tech|Microsoft|microsoft|microsoft
Big tech|Google|google|google
Big tech|Amazon|amazon|amazon
Big tech|Meta|jsearch|Meta
Big tech|Netflix|eightfold|explore.jobs.netflix.net|netflix.com
Big tech|Oracle|oraclehcm|eeho.fa.us2.oraclecloud.com|CX_45001
Big tech|Tesla|jsearch|Tesla
Big tech|IBM|jsearch|IBM
Big tech|Cisco|jsearch|Cisco
Big tech|LinkedIn|jsearch|LinkedIn
Big tech|TikTok|jsearch|TikTok
Big tech|Samsung|jsearch|Samsung
AI|OpenAI|ashby|openai
AI|Anthropic|greenhouse|anthropic
AI|xAI|greenhouse|xai
AI|Scale AI|greenhouse|scaleai
AI|Cohere|ashby|cohere
AI|Perplexity|ashby|perplexity
AI|Hugging Face|workable|huggingface
AI|Databricks|greenhouse|databricks
AI|Palantir|lever|palantir
AI|Mistral AI|jsearch|Mistral AI
Chips & hardware|NVIDIA|workday|nvidia|wd5|NVIDIAExternalCareerSite
Chips & hardware|Intel|workday|intel|wd1|External
Chips & hardware|AMD|jsearch|AMD
Chips & hardware|Qualcomm|jsearch|Qualcomm
Chips & hardware|Broadcom|workday|broadcom|wd1|External_Career
Chips & hardware|Micron|workday|micron|wd1|External
Chips & hardware|Texas Instruments|jsearch|Texas Instruments
Chips & hardware|Applied Materials|jsearch|Applied Materials
Chips & hardware|Lam Research|jsearch|Lam Research
Chips & hardware|KLA|workday|kla|wd1|Search
Chips & hardware|Analog Devices|workday|analogdevices|wd1|External
Chips & hardware|Marvell|workday|marvell|wd1|MarvellCareers
Chips & hardware|Arm|jsearch|Arm
Chips & hardware|Synopsys|jsearch|Synopsys
Chips & hardware|Cadence|workday|cadence|wd1|External_Careers
Chips & hardware|Western Digital|smartrecruiters|Westerndigital
Chips & hardware|Dell|jsearch|Dell
Chips & hardware|HP|workday|hp|wd5|ExternalCareerSite
Chips & hardware|Hewlett Packard Enterprise|jsearch|Hewlett Packard Enterprise
Chips & hardware|Motorola Solutions|workday|motorolasolutions|wd5|Careers
Enterprise software & cloud|Salesforce|workday|salesforce|wd12|External_Career_Site
Enterprise software & cloud|Adobe|workday|adobe|wd5|external_experienced
Enterprise software & cloud|ServiceNow|smartrecruiters|Servicenow
Enterprise software & cloud|Workday|workday|workday|wd5|Workday
Enterprise software & cloud|Intuit|jsearch|Intuit
Enterprise software & cloud|Autodesk|workday|autodesk|wd1|Ext
Enterprise software & cloud|Snowflake|ashby|snowflake
Enterprise software & cloud|Atlassian|jsearch|Atlassian
Enterprise software & cloud|Red Hat|workday|redhat|wd5|Jobs
Enterprise software & cloud|VMware|jsearch|VMware
Enterprise software & cloud|Splunk|jsearch|Splunk
Enterprise software & cloud|Zoom|jsearch|Zoom
Enterprise software & cloud|Twilio|greenhouse|twilio
Enterprise software & cloud|Dropbox|greenhouse|dropbox
Enterprise software & cloud|Datadog|greenhouse|datadog
Enterprise software & cloud|MongoDB|greenhouse|mongodb
Enterprise software & cloud|Elastic|greenhouse|elastic
Enterprise software & cloud|Confluent|jsearch|Confluent
Enterprise software & cloud|GitLab|greenhouse|gitlab
Enterprise software & cloud|GitHub|jsearch|GitHub
Enterprise software & cloud|Cloudflare|greenhouse|cloudflare
Enterprise software & cloud|Akamai|jsearch|Akamai
Security|Palo Alto Networks|jsearch|Palo Alto Networks
Security|CrowdStrike|workday|crowdstrike|wd5|crowdstrikecareers
Security|Fortinet|jsearch|Fortinet
Security|Zscaler|greenhouse|zscaler
Security|Okta|greenhouse|okta
Security|SentinelOne|jsearch|SentinelOne
Internet & consumer|Uber|jsearch|Uber
Internet & consumer|Airbnb|greenhouse|airbnb
Internet & consumer|DoorDash|jsearch|DoorDash
Internet & consumer|Lyft|greenhouse|lyft
Internet & consumer|Instacart|greenhouse|instacart
Internet & consumer|Shopify|jsearch|Shopify
Internet & consumer|Spotify|lever|spotify
Internet & consumer|Pinterest|greenhouse|pinterest
Internet & consumer|Snap|workday|snapchat|wd1|snap
Internet & consumer|Reddit|greenhouse|reddit
Internet & consumer|Discord|greenhouse|discord
Internet & consumer|eBay|jsearch|eBay
Internet & consumer|Etsy|workday|etsy|wd5|Etsy_Careers
Internet & consumer|Zillow|workday|zillow|wd5|Zillow_Group_External
Internet & consumer|Roblox|greenhouse|roblox
Internet & consumer|Electronic Arts|jsearch|Electronic Arts
Internet & consumer|Epic Games|greenhouse|epicgames
Fintech|Stripe|greenhouse|stripe
Fintech|PayPal|workday|paypal|wd1|jobs
Fintech|Block|greenhouse|block
Fintech|Coinbase|greenhouse|coinbase
Fintech|Robinhood|greenhouse|robinhood
Fintech|Visa|workday|visa|wd5|Visa
Fintech|Mastercard|workday|mastercard|wd1|CorporateCareers
Fintech|Capital One|workday|capitalone|wd12|Capital_One
Fintech|Bloomberg|jsearch|Bloomberg
Autonomy & space|Waymo|greenhouse|waymo
Autonomy & space|SpaceX|greenhouse|spacex
Autonomy & space|General Motors|workday|generalmotors|wd5|Careers_GM
"""

TOP_TECH: list[dict] = [
    {"category": c, "company": n, "kind": k, "identifier": i, "via": "google_jobs" if k == "jsearch" else "direct"}
    for c, n, k, i in (line.split("|", 3) for line in _TOP.strip().splitlines())
]
