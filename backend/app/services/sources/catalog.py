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
Big tech|Cisco|workday|cisco|wd5|Cisco_Careers
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
Chips & hardware|AMD|jibe|careers.amd.com
Chips & hardware|Qualcomm|eightfold|qualcomm.eightfold.ai|qualcomm.com
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
Chips & hardware|Lenovo|avature|jobs.lenovo.com/en_US/careers
Autonomy & space|Toyota|workday|toyota|wd503|TMNA
Banking & finance|JPMorgan Chase|oraclehcm|jpmc.fa.oraclecloud.com|CX_1001
Banking & finance|Goldman Sachs|jsearch|Goldman Sachs
Banking & finance|Morgan Stanley|eightfold|morganstanley.eightfold.ai|morganstanley.com
Banking & finance|Citi|workday|citi|wd5|2
Banking & finance|Bank of America|workday|ghr|wd1|lateral-us
Consulting & IT services|Accenture|workday|accenture|wd103|AccentureCareers
Consulting & IT services|Deloitte|avature|apply.deloitte.com/en_US/careers
Consulting & IT services|Wipro|jsearch|Wipro
Consulting & IT services|Infosys|jsearch|Infosys
Consulting & IT services|Tata Consultancy Services|jsearch|Tata Consultancy Services
Consulting & IT services|Cognizant|jsearch|Cognizant
Consulting & IT services|HCLTech|jsearch|HCLTech
Consulting & IT services|Capgemini|jsearch|Capgemini
Consulting & IT services|Tech Mahindra|jsearch|Tech Mahindra
Healthcare & pharma|Abbott|workday|abbott|wd5|abbottcareers
Healthcare & pharma|Amgen|workday|amgen|wd1|Careers
Healthcare & pharma|BD|workday|bdx|wd1|EXTERNAL_CAREER_SITE_USA
Healthcare & pharma|Bristol Myers Squibb|workday|bristolmyerssquibb|wd5|BMS
Healthcare & pharma|CVS Health|workday|cvshealth|wd1|CVS_Health_Careers
Healthcare & pharma|Cardinal Health|workday|cardinalhealth|wd1|EXT
Healthcare & pharma|Centene|workday|centene|wd5|Centene_External
Healthcare & pharma|Cigna|workday|cigna|wd5|cignacareers
Healthcare & pharma|Danaher|workday|danaher|wd1|DanaherJobs
Healthcare & pharma|Elevance Health|workday|elevancehealth|wd1|ANT
Healthcare & pharma|Eli Lilly|jsearch|Eli Lilly
Healthcare & pharma|GE HealthCare|workday|gehc|wd5|GEHC_ExternalSite
Healthcare & pharma|Gilead|workday|gilead|wd1|gileadcareers
Healthcare & pharma|Humana|workday|humana|wd5|Humana_External_Career_Site
Healthcare & pharma|Illumina|workday|illumina|wd1|illumina-careers
Healthcare & pharma|Johnson & Johnson|workday|jj|wd5|JJ
Healthcare & pharma|Labcorp|workday|labcorp|wd1|External
Healthcare & pharma|McKesson|workday|mckesson|wd3|External_Careers
Healthcare & pharma|Medtronic|workday|medtronic|wd1|MedtronicCareers
Healthcare & pharma|Merck|workday|msd|wd5|SearchJobs
Healthcare & pharma|Moderna|workday|modernatx|wd1|M_tx
Healthcare & pharma|Molina Healthcare|oraclehcm|hckd.fa.us2.oraclecloud.com|CX_1
Healthcare & pharma|Oscar Health|greenhouse|oscar
Healthcare & pharma|Pfizer|workday|pfizer|wd1|PfizerCareers
Healthcare & pharma|Philips|workday|philips|wd3|jobs-and-careers
Healthcare & pharma|Quest Diagnostics|oraclehcm|hdox.fa.us6.oraclecloud.com|CX_1
Healthcare & pharma|Stryker|workday|stryker|wd1|StrykerCareers
Healthcare & pharma|Tempus AI|workday|tempus|wd5|Tempus_Careers
Healthcare & pharma|Thermo Fisher Scientific|workday|thermofisher|wd5|ThermoFisherCareers
Healthcare & pharma|UnitedHealth Group (Optum)|jsearch|UnitedHealth Group
Banking & finance|Ally|workday|ally|wd1|Ally
Banking & finance|American Express|jsearch|American Express
Banking & finance|BlackRock|workday|blackrock|wd1|BlackRock_Professional
Banking & finance|CME Group|workday|cmegroup|wd1|cme_careers
Banking & finance|Capital Group|workday|capgroup|wd1|capitalgroupcareers
Banking & finance|Charles Schwab|jsearch|Charles Schwab
Banking & finance|Chime|greenhouse|chime
Banking & finance|FIS|workday|fis|wd5|SearchJobs
Banking & finance|Fannie Mae|workday|fanniemae|wd1|FannieMaeCareers
Banking & finance|Fidelity Investments|workday|fmr|wd1|FidelityCareers
Banking & finance|Fiserv|workday|fiserv|wd5|EXT
Banking & finance|Freddie Mac|workday|freddiemac|wd5|External
Banking & finance|Global Payments|workday|tsys|wd1|TSYS
Banking & finance|Jane Street|greenhouse|janestreet
Banking & finance|Nasdaq|workday|nasdaq|wd1|Global_External_Site
Banking & finance|Northern Trust|workday|ntrs|wd1|northerntrust
Banking & finance|PNC|workday|pnc|wd5|External
Banking & finance|S&P Global|workday|spgi|wd5|SPGI_Careers
Banking & finance|SoFi|greenhouse|sofi
Banking & finance|State Street|workday|statestreet|wd1|Global
Banking & finance|Synchrony|workday|synchronyfinancial|wd5|Careers
Banking & finance|T. Rowe Price|workday|troweprice|wd5|TRowePrice
Banking & finance|Truist|workday|truist|wd1|Careers
Banking & finance|U.S. Bank|workday|usbank|wd1|US_Bank_Careers
Banking & finance|Vanguard|workday|vanguard|wd5|vanguard_external
Banking & finance|Wells Fargo|workday|wf|wd1|WellsFargoJobs
Insurance|Allstate|workday|allstate|wd5|allstate_careers
Insurance|MetLife|lever|metlife
Insurance|Nationwide|workday|nationwide|wd1|Nationwide_Career
Insurance|Prudential|workday|pru|wd5|Careers
Insurance|The Hartford|workday|thehartford|wd5|Careers_External
Insurance|Travelers|workday|travelers|wd5|External
Insurance|USAA|workday|usaa|wd1|USAAJOBSWD
Retail & consumer|Coca-Cola|workday|coke|wd1|coca-cola-careers
Retail & consumer|Expedia|workday|expedia|wd108|search
Retail & consumer|Hilton|oraclehcm|efet.fa.us2.oraclecloud.com|CX_1
Retail & consumer|Macy's|oraclehcm|ebwh.fa.us2.oraclecloud.com|CX_1
Retail & consumer|Nike|workday|nike|wd1|nke
Retail & consumer|Procter & Gamble|workday|pg|wd5|1000
Retail & consumer|Target|workday|target|wd5|targetcareers
Retail & consumer|The Home Depot|workday|homedepot|wd5|CareerDepot
Retail & consumer|Walmart|jsearch|Walmart
Telecom & media|AT&T|workday|att|wd1|ATTGeneral
Telecom & media|Comcast|jsearch|Comcast
Telecom & media|Disney|workday|disney|wd5|disneycareer
Telecom & media|Fox|workday|fox|wd1|Domestic
Telecom & media|Sony|workday|sonyglobal|wd1|SonyGlobalCareers
Telecom & media|T-Mobile|workday|tmobile|wd1|External
Telecom & media|Verizon|workday|verizon|wd12|verizon-careers
Telecom & media|Warner Bros. Discovery|workday|warnerbros|wd5|global
Industrial, aerospace & defense|3M|workday|3m|wd1|Search
Industrial, aerospace & defense|Anduril|greenhouse|andurilindustries
Industrial, aerospace & defense|Boeing|workday|boeing|wd1|EXTERNAL_CAREERS
Industrial, aerospace & defense|Booz Allen Hamilton|workday|bah|wd1|BAH_Jobs
Industrial, aerospace & defense|CACI|workday|caci|wd1|External
Industrial, aerospace & defense|Caterpillar|workday|cat|wd5|CaterpillarCareers
Industrial, aerospace & defense|Chevron|workday|chevron|wd5|jobs
Industrial, aerospace & defense|GE Aerospace|workday|geaerospace|wd5|GE_ExternalSite
Industrial, aerospace & defense|General Dynamics IT|workday|gdit|wd5|External_Career_Site
Industrial, aerospace & defense|Leidos|workday|leidos|wd5|External
Industrial, aerospace & defense|Lockheed Martin|jsearch|Lockheed Martin
Industrial, aerospace & defense|Lucid Motors|greenhouse|lucidmotors
Industrial, aerospace & defense|Northrop Grumman|workday|ngc|wd1|Northrop_Grumman_External_Site
Industrial, aerospace & defense|RTX|workday|globalhr|wd5|REC_RTX_Ext_Gateway
Industrial, aerospace & defense|Stellantis|workday|stellantis|wd3|External_Career_Site_ID01
Enterprise software & cloud|Asana|greenhouse|asana
Enterprise software & cloud|Box|greenhouse|boxinc
Enterprise software & cloud|Ciena|workday|ciena|wd5|Careers
Enterprise software & cloud|CoreWeave|greenhouse|coreweave
Enterprise software & cloud|Equifax|workday|equifax|wd5|External
Enterprise software & cloud|Experian|smartrecruiters|Experian
Enterprise software & cloud|Figma|greenhouse|figma
Enterprise software & cloud|Fivetran|greenhouse|fivetran
Enterprise software & cloud|Gartner|workday|gartner|wd5|EXT
Enterprise software & cloud|Glean|greenhouse|gleanwork
Enterprise software & cloud|HubSpot|greenhouse|hubspotjobs
Enterprise software & cloud|Lambda|ashby|lambda
Enterprise software & cloud|Notion|ashby|notion
Enterprise software & cloud|Pure Storage|greenhouse|purestorage
Enterprise software & cloud|RELX (LexisNexis)|workday|relx|wd3|relx
Enterprise software & cloud|Rubrik|greenhouse|rubrik
Enterprise software & cloud|Samsara|greenhouse|samsara
Enterprise software & cloud|Thomson Reuters|workday|thomsonreuters|wd5|External_Career_Site
Enterprise software & cloud|Toast|greenhouse|toast
Enterprise software & cloud|TransUnion|workday|transunion|wd5|TransUnion
Enterprise software & cloud|UiPath|ashby|uipath
Enterprise software & cloud|Veeva Systems|lever|veeva
Consulting & IT services|DXC Technology|workday|dxctechnology|wd1|DXCJobs
Consulting & IT services|Genpact|workday|genpact|wd108|External_Careers
Consulting & IT services|Kyndryl|workday|kyndryl|wd5|KyndrylProfessionalCareers
Consulting & IT services|PwC|workday|pwc|wd3|Global_Experienced_Careers
Consulting & IT services|Thoughtworks|greenhouse|thoughtworks
"""

TOP_TECH: list[dict] = [
    {"category": c, "company": n, "kind": k, "identifier": i, "via": "google_jobs" if k == "jsearch" else "direct"}
    for c, n, k, i in (line.split("|", 3) for line in _TOP.strip().splitlines())
]
