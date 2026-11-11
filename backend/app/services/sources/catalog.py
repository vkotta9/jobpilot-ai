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


# The 2026 Fortune 500 (published by Fortune on June 3, 2026), by rank. Line format: rank|company|aliases (;)|kind|identifier.
# Direct feeds were found and verified from GitHub Actions in Nov 2026 (scripts/scan_companies.py on scripts/scan_f500*.txt,
# then scripts/verify_feeds.py, which opens postings and checks the company's name appears in them; matches like Liberty
# University or Owens Community College were rejected). Companies without a verified feed are followed through Google Jobs
# (JSearch): their identifier is the name as Google Jobs lists the employer, since every word must appear there.
_F500 = """
1|Amazon||amazon|amazon
2|Walmart||jsearch|Walmart
3|UnitedHealth Group||jsearch|UnitedHealth Group
4|Apple||apple|apple
5|Alphabet|Google|google|google
6|CVS Health||workday|cvshealth|wd1|CVS_Health_Careers
7|Berkshire Hathaway||jsearch|Berkshire Hathaway
8|McKesson||workday|mckesson|wd3|External_Careers
9|Exxon Mobil|ExxonMobil;Exxon|jsearch|ExxonMobil
10|Cencora|AmerisourceBergen|jsearch|Cencora
11|Microsoft||microsoft|microsoft
12|JPMorgan Chase||oraclehcm|jpmc.fa.oraclecloud.com|CX_1001
13|Costco Wholesale||jsearch|Costco
14|Cigna Group||workday|cigna|wd5|cignacareers
15|Cardinal Health||workday|cardinalhealth|wd1|EXT
16|Nvidia||workday|nvidia|wd5|NVIDIAExternalCareerSite
17|Meta Platforms|Meta;Facebook|jsearch|Meta
18|Elevance Health||workday|elevancehealth|wd1|ANT
19|Centene||workday|centene|wd5|Centene_External
20|Bank of America||workday|ghr|wd1|lateral-us
21|Chevron||workday|chevron|wd5|jobs
22|Ford Motor||oraclehcm|efds.fa.em5.oraclecloud.com|CX_1
23|General Motors||workday|generalmotors|wd5|Careers_GM
24|Citigroup||workday|citi|wd5|2
25|Home Depot||workday|homedepot|wd5|CareerDepot
26|Fannie Mae||workday|fanniemae|wd1|FannieMaeCareers
27|Kroger||jsearch|Kroger
28|Verizon Communications||workday|verizon|wd12|verizon-careers
29|Phillips 66||jsearch|Phillips 66
30|Marathon Petroleum||workday|mpc|wd1|MPCCareers
31|StoneX Group||jsearch|StoneX
32|State Farm Insurance||jsearch|State Farm
33|Freddie Mac||workday|freddiemac|wd5|External
34|Humana||workday|humana|wd5|Humana_External_Career_Site
35|AT&T||workday|att|wd1|ATTGeneral
36|Goldman Sachs Group||jsearch|Goldman Sachs
37|Comcast||jsearch|Comcast
38|Wells Fargo||workday|wf|wd1|WellsFargoJobs
39|Morgan Stanley||eightfold|morganstanley.eightfold.ai|morganstanley.com
40|Valero Energy||jsearch|Valero
41|Dell Technologies||jsearch|Dell
42|Target||workday|target|wd5|targetcareers
43|Tesla||jsearch|Tesla
44|Walt Disney||workday|disney|wd5|disneycareer
45|Johnson & Johnson||workday|jj|wd5|JJ
46|PepsiCo||jsearch|PepsiCo
47|Boeing||workday|boeing|wd1|EXTERNAL_CAREERS
48|UPS|United Parcel Service|workday|hcmportal|wd5|Search
49|RTX||workday|globalhr|wd5|REC_RTX_Ext_Gateway
50|FedEx||jsearch|FedEx
51|Progressive||jsearch|Progressive
52|Lowe's|Lowes|jsearch|Lowe's
53|Energy Transfer||jsearch|Energy Transfer
54|Procter & Gamble||workday|pg|wd5|1000
55|Sysco||jsearch|Sysco
56|American Express||jsearch|American Express
57|Albertsons||oraclehcm|eofd.fa.us6.oraclecloud.com|CX_1001
58|Archer Daniels Midland|ADM|jsearch|ADM
59|MetLife||lever|metlife
60|HCA Healthcare||jsearch|HCA Healthcare
61|Lockheed Martin||jsearch|Lockheed Martin
62|New York Life Insurance||jsearch|New York Life
63|Capital One Financial||workday|capitalone|wd12|Capital_One
64|Allstate||workday|allstate|wd5|allstate_careers
65|Caterpillar||workday|cat|wd5|CaterpillarCareers
66|IBM|International Business Machines|jsearch|IBM
67|Eli Lilly||jsearch|Eli Lilly
68|Merck||workday|msd|wd5|SearchJobs
69|Nationwide||workday|nationwide|wd1|Nationwide_Career
70|Broadcom||workday|broadcom|wd1|External_Career
71|Delta Air Lines||jsearch|Delta Air Lines
72|Publix Super Markets||jsearch|Publix
73|Pfizer||workday|pfizer|wd1|PfizerCareers
74|TD Synnex||workday|synnex|wd5|tdsynnexcareers
75|ConocoPhillips||workday|conocophillips|wd1|External
76|Galaxy Digital||jsearch|Galaxy Digital
77|AbbVie||jsearch|AbbVie
78|Prudential Financial||workday|pru|wd5|Careers
79|TJX||jsearch|TJX
80|Performance Food Group||jsearch|Performance Food
81|United Airlines Holdings||jsearch|United Airlines
82|Oracle||oraclehcm|eeho.fa.us2.oraclecloud.com|CX_45001
83|Cisco Systems||workday|cisco|wd5|Cisco_Careers
84|HP||workday|hp|wd5|ExternalCareerSite
85|Charter Communications||jsearch|Charter Communications
86|American Airlines Group||jsearch|American Airlines
87|Tyson Foods||workday|tysonfoods|wd5|TSN
88|Intel||workday|intel|wd1|External
89|Enterprise Products Partners||jsearch|Enterprise Products
90|Ingram Micro||workday|ingrammicro|wd5|IngramMicro
91|General Dynamics||workday|gdit|wd5|External_Career_Site
92|Uber Technologies||jsearch|Uber
93|USAA|United Services Automobile Association|workday|usaa|wd1|USAAJOBSWD
94|TIAA||workday|tiaa|wd1|Search
95|Liberty Mutual Insurance||jsearch|Liberty Mutual
96|Travelers||workday|travelers|wd5|External
97|Bristol-Myers Squibb||workday|bristolmyerssquibb|wd5|BMS
98|Coca-Cola||workday|coke|wd1|coca-cola-careers
99|Nike||workday|nike|wd1|nke
100|MassMutual|Massachusetts Mutual Life Insurance|jsearch|MassMutual
101|GE Aerospace||workday|geaerospace|wd5|GE_ExternalSite
102|Deere|John Deere|jsearch|Deere
103|Plains GP Holdings||workday|plains|wd1|Plains
104|Molina Healthcare||oraclehcm|hckd.fa.us2.oraclecloud.com|CX_1
105|Netflix||eightfold|explore.jobs.netflix.net|netflix.com
106|Thermo Fisher Scientific||workday|thermofisher|wd5|ThermoFisherCareers
107|Abbott Laboratories||workday|abbott|wd5|abbottcareers
108|Qualcomm||eightfold|qualcomm.eightfold.ai|qualcomm.com
109|Northwestern Mutual||workday|northwesternmutual|wd5|CORPORATE-CAREERS
110|U.S. Bancorp||workday|usbank|wd1|US_Bank_Careers
111|Dollar General||oraclehcm|ibxwjb.fa.ocs.oraclecloud.com|CX_1
112|Northrop Grumman||workday|ngc|wd1|Northrop_Grumman_External_Site
113|Best Buy||jsearch|Best Buy
114|Salesforce||workday|salesforce|wd12|External_Career_Site
115|BNY|BNY Mellon;Bank of New York|jsearch|BNY
116|Honeywell|Honeywell Technologies|jsearch|Honeywell
117|Philip Morris International||jsearch|Philip Morris
118|CBRE Group||jsearch|CBRE
119|Visa||workday|visa|wd5|Visa
120|Dow||workday|dow|wd1|ExternalCareers
121|US Foods||jsearch|US Foods
122|Mondelez International|Mondelez|jsearch|Mondelez
123|Lithia Motors||jsearch|Lithia Motors
124|GE Vernova||workday|gevernova|wd5|Vernova_ExternalSite
125|Micron Technology||workday|micron|wd1|External
126|Warner Bros. Discovery||workday|warnerbros|wd5|global
127|Starbucks||jsearch|Starbucks
128|World Kinect||workday|wfscorp|wd5|wfscareers
129|Amgen||workday|amgen|wd1|Careers
130|CHS||jsearch|CHS
131|AMD|Advanced Micro Devices|jibe|careers.amd.com
132|Coupang||greenhouse|coupang
133|Hewlett Packard Enterprise||jsearch|Hewlett Packard Enterprise
134|D.R. Horton||jsearch|D.R. Horton
135|Lennar||workday|lennar|wd1|Lennar_Jobs
136|PNC Financial Services||workday|pnc|wd5|External
137|Cummins||oraclehcm|fa-espx-saasfaprod1.fa.ocs.oraclecloud.com|CX_1
138|Oneok||workday|oneok|wd1|ONEOK
139|PayPal||workday|paypal|wd1|jobs
140|GuideWell Mutual Holding||oraclehcm|fa-etum-saasfaprod1.fa.ocs.oraclecloud.com|CX_1
141|Mastercard||workday|mastercard|wd1|CorporateCareers
142|Nucor||jsearch|Nucor
143|Apollo Global Management||workday|athene|wd5|Apollo_Careers
144|Penske Automotive Group||jsearch|Penske Automotive
145|Duke Energy||workday|dukeenergy|wd1|Search
146|United Natural Foods||jsearch|United Natural Foods
147|Ferguson Enterprises||workday|ferguson|wd1|Ferguson_Experienced
148|Arrow Electronics||workday|arrow|wd1|AC
149|NRG Energy||jsearch|NRG Energy
150|Truist Financial||workday|truist|wd1|Careers
151|Jabil||workday|jabil|wd5|Jabil_Careers
152|Southern Company||jsearch|Southern Company
153|Gilead Sciences||workday|gilead|wd1|gileadcareers
154|PBF Energy||workday|pbfenergy|wd1|PBF
155|Paramount Skydance||jsearch|Paramount Skydance
156|KKR||jsearch|KKR
157|Quanta Services||jsearch|Quanta Services
158|Paccar||jsearch|Paccar
159|Medline||workday|medline|wd5|Medline
160|Applied Materials||jsearch|Applied Materials
160|Hartford Insurance Group|The Hartford|workday|thehartford|wd5|Careers_External
162|CarMax||workday|carmax|wd1|External
163|Southwest Airlines||jsearch|Southwest Airlines
164|Baker Hughes||workday|bakerhughes|wd5|BakerHughes
165|Charles Schwab||jsearch|Charles Schwab
166|AutoNation||jsearch|AutoNation
167|NextEra Energy||jsearch|NextEra Energy
168|Marsh McLennan|Marsh & McLennan|jsearch|Marsh McLennan
169|Booking Holdings||jsearch|Booking
170|McDonald's||jsearch|McDonald's
171|HF Sinclair||jsearch|HF Sinclair
172|AIG||workday|aig|wd1|aig
173|Occidental Petroleum||workday|oxy|wd5|Corporate
174|Marriott International||jsearch|Marriott
175|JLL|Jones Lang LaSalle|workday|jll|wd1|jllcareers
176|International Paper||jsearch|International Paper
177|Freeport-McMoRan||jsearch|Freeport-McMoRan
178|Constellation Energy||jsearch|Constellation Energy
179|Waste Management||jsearch|Waste Management
180|Live Nation Entertainment||workday|livenation|wd503|LNExternalSite
181|Stryker||workday|stryker|wd1|StrykerCareers
182|Dollar Tree||workday|dollartree|wd5|dollartreeus
183|3M||workday|3m|wd1|Search
184|Kraft Heinz||jsearch|Kraft Heinz
185|PG&E||jsearch|PG&E
186|Danaher||workday|danaher|wd1|DanaherJobs
187|Union Pacific||jsearch|Union Pacific
188|Genuine Parts||jsearch|Genuine Parts
189|Exelon||jsearch|Exelon
190|BlackRock||workday|blackrock|wd1|BlackRock_Professional
191|Block||greenhouse|block
192|Adobe||workday|adobe|wd5|external_experienced
193|Reinsurance Group of America||jsearch|RGA
194|Sherwin-Williams||jsearch|Sherwin-Williams
195|WESCO International||jsearch|WESCO
196|Lear||jsearch|Lear Corporation
197|Synchrony||workday|synchronyfinancial|wd5|Careers
198|Amphenol||jsearch|Amphenol
199|Ross Stores||jsearch|Ross Stores
200|Newmont||jsearch|Newmont
201|EOG Resources||jsearch|EOG Resources
202|State Street||workday|statestreet|wd1|Global
203|Macy's||oraclehcm|ebwh.fa.us2.oraclecloud.com|CX_1
204|Group 1 Automotive||jsearch|Group 1 Automotive
205|CDW||workday|cdw|wd5|Careers
206|Avnet||jsearch|Avnet
207|Halliburton||jsearch|Halliburton
208|Super Micro Computer||jsearch|Supermicro
209|American Electric Power||workday|aep|wd1|AEPCareerSite
210|L3Harris Technologies||jsearch|L3Harris
211|Becton Dickinson||workday|bdx|wd1|EXTERNAL_CAREER_SITE_USA
212|Carrier Global||workday|carrier|wd5|jobs
213|BJ's Wholesale Club||workday|bjswholesaleclub|wd1|BJsCareers
214|Tenet Healthcare||jsearch|Tenet Healthcare
215|Fiserv||workday|fiserv|wd5|EXT
216|Cognizant||jsearch|Cognizant
217|GE HealthCare||workday|gehc|wd5|GEHC_ExternalSite
218|ADP|Automatic Data Processing|jsearch|ADP
219|Colgate-Palmolive||jsearch|Colgate-Palmolive
220|Carvana||greenhouse|carvana
221|Altria Group||jsearch|Altria
222|Boston Scientific||jsearch|Boston Scientific
223|Cheniere Energy||jsearch|Cheniere
224|Parker-Hannifin||jsearch|Parker Hannifin
225|Kimberly-Clark||jsearch|Kimberly-Clark
226|American Family Insurance||workday|amfam|wd1|Careers
227|General Mills||workday|genmills|wd1|GMI_External_Careers
228|Edison International||jsearch|Edison
229|AutoZone||jsearch|AutoZone
230|Ameriprise Financial||workday|ameriprise|wd5|Ameriprise
231|Intuit||jsearch|Intuit
232|Guardian Life||workday|guardianlife|wd5|Guardian-Life-Careers
233|Cleveland-Cliffs||jsearch|Cleveland-Cliffs
234|Global Partners||jsearch|Global Partners
235|Aramark||jsearch|Aramark
236|Corebridge Financial||workday|corebridgefinancial|wd1|CorebridgeFinancial
237|Loews||jsearch|Loews
238|Lam Research||jsearch|Lam Research
239|Goodyear Tire & Rubber||workday|goodyear|wd1|GoodyearCareers
240|Pacific Life||workday|pacificlife|wd1|PacificLifeCareers
241|Auto-Owners Insurance||jsearch|Auto-Owners
242|Kiewit|Peter Kiewit Sons|jsearch|Kiewit
243|Lincoln Financial|Lincoln National|jsearch|Lincoln Financial
244|Steel Dynamics||jsearch|Steel Dynamics
245|Emerson Electric||jsearch|Emerson
246|Asbury Automotive Group||jsearch|Asbury Automotive
247|ManpowerGroup||jsearch|ManpowerGroup
248|W.W. Grainger||jsearch|Grainger
249|Edward Jones|Jones Financial|jsearch|Edward Jones
250|O'Reilly Automotive||workday|oreillyauto|wd1|oreilly
251|Vistra||jsearch|Vistra
252|Texas Instruments||jsearch|Texas Instruments
253|MGM Resorts International||jsearch|MGM Resorts
254|Corteva||jsearch|Corteva
255|Universal Health Services||jsearch|Universal Health
256|PulteGroup||workday|pultegroup|wd1|PGI
257|Omnicom Group||jsearch|Omnicom
258|Dick's Sporting Goods||workday|dickssportinggoods|wd1|DSG
259|Devon Energy||jsearch|Devon Energy
260|Leidos||workday|leidos|wd5|External
261|Aflac||jsearch|Aflac
262|Targa Resources||jsearch|Targa Resources
263|Murphy USA||jsearch|Murphy USA
264|LPL Financial||workday|lplfinancial|wd1|External
265|EMCOR Group||jsearch|EMCOR
266|Kinder Morgan||jsearch|Kinder Morgan
267|Consolidated Edison||jsearch|Consolidated Edison
268|Keurig Dr Pepper||jsearch|Keurig Dr Pepper
269|Republic Services||workday|republic|wd5|Republic
270|Markel Group||jsearch|Markel
271|Farmers Insurance||jsearch|Farmers Insurance
272|Dominion Energy||jsearch|Dominion Energy
273|Land O'Lakes||workday|landolakes|wd1|LandOLakes
274|IQVIA||workday|iqvia|wd1|IQVIA
275|Fox||workday|fox|wd1|Domestic
276|AECOM||jsearch|AECOM
277|C.H. Robinson||workday|chrobinson|wd5|CHRobinson
278|BitGo||greenhouse|bitgo
279|United Rentals||workday|ur|wd1|URcareers
280|Ecolab||jsearch|Ecolab
281|Illinois Tool Works||jsearch|Illinois Tool Works
282|Casey's General Stores||jsearch|Casey's General Stores
283|Raymond James Financial||workday|raymondjames|wd1|RaymondJamesCareers
284|PPG Industries||jsearch|PPG
285|DTE Energy||jsearch|DTE Energy
286|Corning||jsearch|Corning
287|Principal Financial||jsearch|Principal Financial
288|Mutual of Omaha||jsearch|Mutual of Omaha
289|Kohl's||workday|kohls|wd504|kohlscareers
290|Tractor Supply||jsearch|Tractor Supply
291|Whirlpool||eightfold|whirlpool.eightfold.ai|whirlpool.com
292|Fluor||jsearch|Fluor
293|Gap||jsearch|Gap Inc
294|S&P Global||workday|spgi|wd5|SPGI_Careers
295|Ally Financial||workday|ally|wd1|Ally
296|Builders FirstSource||jsearch|Builders FirstSource
297|Sonic Automotive||jsearch|Sonic Automotive
298|Stanley Black & Decker||jsearch|Stanley Black & Decker
299|Kenvue||jsearch|Kenvue
300|Kyndryl||workday|kyndryl|wd5|KyndrylProfessionalCareers
301|Diamondback Energy||workday|diamondbackenergy|wd12|DBE
302|EchoStar||jsearch|EchoStar
303|Textron||jsearch|Textron
304|Expedia Group||workday|expedia|wd108|search
305|W.R. Berkley||jsearch|W.R. Berkley
306|Xcel Energy||workday|xcelenergy|wd1|External
307|FirstEnergy||jsearch|FirstEnergy
308|Erie Insurance Group||jsearch|Erie Insurance
309|First Citizens BancShares||jsearch|First Citizens
310|Blackstone||workday|blackstone|wd1|Blackstone_Careers
311|Fidelity National Financial||jsearch|Fidelity National Financial
312|Otis Worldwide||jsearch|Otis
313|Amentum||jsearch|Amentum
314|Regeneron Pharmaceuticals||workday|regeneron|wd1|Careers
315|Estee Lauder|Estée Lauder|jsearch|Lauder
316|BorgWarner||workday|borgwarner|wd5|BorgWarner_Careers
317|Northern Trust||workday|ntrs|wd1|northerntrust
318|Viatris||workday|viatris|wd5|External
319|MasTec||jsearch|MasTec
320|Reliance||jsearch|Reliance Steel
321|Western & Southern Financial Group||jsearch|Western & Southern
322|Alaska Air Group||jsearch|Alaska Air
323|BrightSpring Health Services||jsearch|BrightSpring Health
324|CSX||jsearch|CSX
325|LKQ||jsearch|LKQ
326|Labcorp||workday|labcorp|wd1|External
327|Arthur J. Gallagher||jsearch|Gallagher
328|Venture Global||jsearch|Venture Global
329|DoorDash||jsearch|DoorDash
330|Sempra||jsearch|Sempra
331|DaVita||workday|davita|wd1|DKC_External
332|Eversource Energy||workday|eversource|wd1|ExternalSite
333|ServiceNow||smartrecruiters|Servicenow
334|M&T Bank||workday|mtb|wd5|MTB
335|Henry Schein||workday|henryschein|wd1|External_Careers
336|GXO Logistics||jsearch|GXO Logistics
337|Ball||jsearch|Ball Corporation
338|Unum Group||workday|unum|wd1|External
339|Las Vegas Sands||workday|sands|wd1|sands_careers
340|Entergy||jsearch|Entergy
341|Fifth Third Bancorp||workday|fifththird|wd5|53careers
342|Graybar Electric||workday|graybar|wd1|Careers
343|DXC Technology||workday|dxctechnology|wd1|DXCJobs
344|Alcoa||workday|alcoa|wd5|Careers
345|Assurant||workday|assurant|wd1|Assurant_Careers
346|Ryder System||workday|ryder|wd5|RyderCareers
347|Intercontinental Exchange||jsearch|Intercontinental Exchange
348|Cincinnati Financial||jsearch|Cincinnati Financial
349|Chewy||jsearch|Chewy
350|Community Health Systems||jsearch|Community Health Systems
350|Huntington Bancshares||workday|huntington|wd12|HNBcareers
352|Huntington Ingalls Industries||jsearch|Huntington Ingalls
353|Wayfair||jsearch|Wayfair
354|Lumen Technologies||jsearch|Lumen
355|Ulta Beauty||jsearch|Ulta Beauty
356|Crown Holdings||workday|crownholdings|wd501|CrownHoldings
357|Airbnb||greenhouse|airbnb
358|AES||jsearch|AES
359|Norfolk Southern||jsearch|Norfolk Southern
360|PSEG|Public Service Enterprise Group|jsearch|PSEG
361|KLA||workday|kla|wd1|Search
362|Expand Energy||jsearch|Expand Energy
363|Hormel Foods||jsearch|Hormel Foods
364|Darden Restaurants||jsearch|Darden Restaurants
365|Citizens Financial Group||jsearch|Citizens
366|Mosaic||workday|mosaic|wd5|mosaic
367|Hilton||oraclehcm|efet.fa.us2.oraclecloud.com|CX_1
368|Air Products||workday|airproducts|wd5|AP0001
369|Jacobs Solutions||jsearch|Jacobs
370|Vertex Pharmaceuticals||workday|vrtx|wd501|Vertex_Careers
371|J.B. Hunt Transport Services||workday|jbhunt|wd501|Careers
372|Booz Allen Hamilton||workday|bah|wd1|BAH_Jobs
373|Williams Companies||workday|williams|wd5|External
374|Chipotle Mexican Grill||workday|chipotle|wd5|ChipotleCareers
375|Yum China||jsearch|Yum China
376|Oscar Health||greenhouse|oscar
377|Hershey||jsearch|Hershey
378|Motorola Solutions||workday|motorolasolutions|wd5|Careers
379|Equitable Holdings||jsearch|Equitable
380|Avis Budget Group||workday|avisbudget|wd1|ABG_Careers
381|Conagra Brands||workday|conagrabrands|wd1|Careers_US
382|Baxter International||workday|baxter|wd1|baxter
383|Burlington Stores||workday|burlington|wd5|BurlingtonCareers
384|Caesars Entertainment||jsearch|Caesars Entertainment
385|Owens Corning||jsearch|Owens Corning
386|KeyCorp||workday|keybank|wd5|External_Career_Site
387|Thrivent Financial||jsearch|Thrivent
388|Westlake||workday|westlake|wd1|westlake
389|Wabtec|Westinghouse Air Brake|jsearch|Wabtec
390|Molson Coors Beverage||jsearch|Molson Coors
391|Lululemon||jsearch|lululemon
392|FM|FM Global|jsearch|FM Global
393|eBay||jsearch|eBay
394|Expeditors International||jsearch|Expeditors
395|Quest Diagnostics||oraclehcm|hdox.fa.us6.oraclecloud.com|CX_1
396|Analog Devices||workday|analogdevices|wd1|External
397|The Andersons||jsearch|Andersons
398|Gold.com||jsearch|Gold.com
399|Toll Brothers||jsearch|Toll Brothers
400|International Flavors & Fragrances||workday|iff|wd5|IFF_Careers
401|Welltower||jsearch|Welltower
402|Jefferies Financial Group||jsearch|Jefferies
403|Autoliv||jsearch|Autoliv
404|Mohawk Industries||jsearch|Mohawk
405|Delek US Holdings||jsearch|Delek
406|FIS|Fidelity National Information Services|workday|fis|wd5|SearchJobs
407|Accendra Health|Owens & Minor|workday|owensminor|wd1|OMCareers
408|American Tower||jsearch|American Tower
409|NVR||jsearch|NVR
410|Interactive Brokers Group||jsearch|Interactive Brokers
411|Oshkosh||jsearch|Oshkosh
412|Cintas||jsearch|Cintas
413|Campbell's||workday|campbellsoup|wd5|ExternalCareers_GlobalSite
414|Vertiv||jsearch|Vertiv
415|Global Payments||workday|tsys|wd1|TSYS
416|Constellation Brands||workday|cbrands|wd5|CBI_External_Careers
417|AGCO||jsearch|AGCO
418|Intuitive Surgical||jsearch|Intuitive Surgical
419|Ace Hardware||workday|acehardware|wd1|External
420|Dana||jsearch|Dana Incorporated
421|Biogen||jsearch|Biogen
422|News Corp|Dow Jones|workday|dowjones|wd1|Dow_Jones_Career
423|Concentrix||jsearch|Concentrix
424|WEC Energy Group||jsearch|WEC Energy
425|VF Corporation||workday|vfc|wd5|vfc_careers
426|Seaboard||jsearch|Seaboard
427|Icahn Enterprises||jsearch|Icahn Enterprises
428|Regions Financial||jsearch|Regions
429|Thor Industries||jsearch|Thor Industries
430|Workday||workday|workday|wd5|Workday
431|Celanese||jsearch|Celanese
432|Western Digital||smartrecruiters|Westerndigital
433|QVC Group||jsearch|QVC
434|Zoetis||workday|zoetis|wd5|zoetis
435|CenterPoint Energy||jsearch|CenterPoint Energy
436|Equinix||jsearch|Equinix
437|Palo Alto Networks||jsearch|Palo Alto Networks
438|APA||jsearch|APA Corporation
439|Old Republic International||workday|oldrepublic|wd1|oldrepublictitle
440|Comfort Systems USA||workday|comfortsystemsusa|wd1|Corpcareers
441|JetBlue Airways||jsearch|JetBlue Airways
442|PPL||jsearch|PPL
443|Xylem||jsearch|Xylem
444|Arista Networks||jsearch|Arista Networks
445|Packaging Corp. of America||jsearch|Packaging Corporation of America
446|PVH||workday|pvh|wd1|PVH_Careers
447|Ovintiv||workday|ovintiv|wd3|ovintivcareers
448|Avery Dennison||jsearch|Avery Dennison
449|TransDigm Group||jsearch|TransDigm
450|Sprouts Farmers Market||jsearch|Sprouts
451|Prologis||workday|prologis|wd5|Prologis_External_Careers
452|Franklin Templeton||jsearch|Franklin Templeton
453|Eastman Chemical||jsearch|Eastman Chemical
454|ABM Industries||jsearch|ABM
455|NOV||jsearch|NOV
456|J.M. Smucker||workday|smucker|wd5|US_External_Careers
457|Securian Financial Group||jsearch|Securian
458|EQT||jsearch|EQT
459|CACI International||workday|caci|wd1|External
460|Graphic Packaging||jsearch|Graphic Packaging
461|Advance Auto Parts||jsearch|Advance Auto Parts
462|Optimum Communications||jsearch|Optimum
463|Sirius XM||jsearch|SiriusXM
464|CMS Energy||jsearch|CMS Energy
465|Hertz||jsearch|Hertz
466|Ameren||workday|ameren|wd1|External
467|Rockwell Automation||workday|rockwellautomation|wd1|External_Rockwell_Automation
468|Solventum||jsearch|Solventum
469|Monster Beverage||jsearch|Monster Beverage
470|Nasdaq||workday|nasdaq|wd1|Global_External_Site
471|Howmet Aerospace||jsearch|Howmet Aerospace
472|Insight Enterprises||jsearch|Insight Enterprises
473|Zimmer Biomet||jsearch|Zimmer Biomet
474|Yum Brands||jsearch|Yum
475|Fastenal||jsearch|Fastenal
476|Marvell Technology||workday|marvell|wd1|MarvellCareers
477|Voya Financial||jsearch|Voya
478|American Financial Group||jsearch|American Financial Group
479|Post Holdings||jsearch|Post Holdings
480|XPO||jsearch|XPO
481|DuPont||workday|dupont|wd5|Jobs
482|Sanmina||jsearch|Sanmina
483|Taylor Morrison||workday|taylormorrison|wd1|TaylorMorrisonCareers
484|Dover||workday|dover|wd103|Dover
485|Vulcan Materials||jsearch|Vulcan Materials
486|APi Group||jsearch|APi Group
487|Roper Technologies||jsearch|Roper
488|KBR||workday|kbr|wd5|KBR_Careers
489|Sonoco Products||workday|sonoco|wd1|CorporateCareers
490|Williams-Sonoma||jsearch|Williams-Sonoma
491|Commercial Metals||jsearch|Commercial Metals
492|Moody's||jsearch|Moody's
493|Continental Resources||workday|clr|wd5|CLR_Careers
494|Ingersoll Rand||jsearch|Ingersoll Rand
495|Core & Main||workday|coreandmain|wd1|coreandmain
496|Coterra Energy||jsearch|Coterra
497|Primoris Services||jsearch|Primoris
498|Masco||jsearch|Masco
499|Somnigroup International|Tempur Sealy|jsearch|Somnigroup
500|Resideo Technologies||jsearch|Resideo
"""


def _band(rank: int) -> str:
    lo = (rank - 1) // 100 * 100 + 1
    return f"Ranks {lo}–{lo + 99}"


FORTUNE_500: list[dict] = [
    {"rank": int(r), "category": _band(int(r)), "company": n, "aliases": [a for a in al.split(";") if a], "kind": k,
     "identifier": i, "via": "google_jobs" if k == "jsearch" else "direct"}
    for r, n, al, k, i in (line.split("|", 4) for line in _F500.strip().splitlines())
]


# Venture-backed startups (seed to late stage), by sector. Line format: category|company|kind|identifier.
# Found by scanning ~400 startups' Ashby / Greenhouse / Lever / Workday boards from GitHub Actions in Nov 2026
# (scripts/scan_startups.txt) and verified by opening postings (scripts/verify_feeds.py) and checking titles and
# locations by hand; lookalikes were rejected (e.g. "Neon" was a Brazilian fintech, "Sila" an HVAC firm).
# All are direct feeds: free, checked daily, no JSearch quota.
_STARTUPS = """
AI & ML|Abridge|ashby|abridge
AI & ML|Ambience Healthcare|ashby|ambiencehealthcare
AI & ML|AssemblyAI|greenhouse|assemblyai
AI & ML|Black Forest Labs|ashby|black-forest-labs
AI & ML|Bland AI|ashby|bland
AI & ML|Cartesia|ashby|cartesia
AI & ML|Character.AI|ashby|character
AI & ML|Cognition|ashby|cognition
AI & ML|Decagon|ashby|decagon
AI & ML|Deepgram|ashby|deepgram
AI & ML|Descript|greenhouse|descript
AI & ML|Elicit|ashby|elicit
AI & ML|Factory|ashby|factory
AI & ML|Gamma|ashby|gamma
AI & ML|Harvey AI|ashby|harvey
AI & ML|HeyGen|greenhouse|heygen
AI & ML|Hume AI|greenhouse|humeai
AI & ML|Imbue|greenhouse|imbue
AI & ML|Invisible Technologies|greenhouse|invisible
AI & ML|Labelbox|greenhouse|labelbox
AI & ML|Liquid AI|ashby|liquid-ai
AI & ML|Lovable|ashby|lovable
AI & ML|Luma AI|ashby|lumaai
AI & ML|Mercor|ashby|mercor
AI & ML|OpenEvidence|ashby|openevidence
AI & ML|Physical Intelligence|ashby|physicalintelligence
AI & ML|Pika|ashby|pika
AI & ML|Poolside|ashby|poolside
AI & ML|Read AI|ashby|read-ai
AI & ML|Reka|ashby|reka
AI & ML|Retell AI|ashby|retell-ai
AI & ML|Rogo|ashby|rogo
AI & ML|Sesame|ashby|sesame
AI & ML|Sierra|ashby|sierra
AI & ML|Snorkel AI|greenhouse|snorkelai
AI & ML|Speak|ashby|speak
AI & ML|Suno|ashby|suno
AI & ML|Surge AI|ashby|surge-ai
AI & ML|Synthesia|ashby|synthesia
AI & ML|Thinking Machines Lab|ashby|thinkingmachines
AI & ML|Turing|greenhouse|turing
AI & ML|Typeface|greenhouse|typeface
AI & ML|Vapi|ashby|vapi
AI & ML|World Labs|ashby|worldlabs
AI & ML|Writer|ashby|writer
AI & ML|You.com|greenhouse|youcom
AI infrastructure|Anyscale|ashby|anyscale
AI infrastructure|Arize AI|greenhouse|arizeai
AI infrastructure|Baseten|ashby|baseten
AI infrastructure|Braintrust|ashby|braintrust
AI infrastructure|Crusoe|ashby|crusoe
AI infrastructure|d-Matrix|ashby|d-matrix
AI infrastructure|Etched|ashby|etched
AI infrastructure|Fireworks AI|ashby|fireworks
AI infrastructure|LangChain|ashby|langchain
AI infrastructure|Lightmatter|greenhouse|lightmatter
AI infrastructure|LlamaIndex|ashby|llamaindex
AI infrastructure|MatX|ashby|matx
AI infrastructure|Nomic|ashby|nomic
AI infrastructure|Runpod|ashby|runpod
AI infrastructure|Tenstorrent|greenhouse|tenstorrent
AI infrastructure|Together AI|greenhouse|togetherai
AI infrastructure|Unstructured|ashby|unstructured
AI infrastructure|Weaviate|ashby|weaviate
AI infrastructure|Zilliz|lever|zilliz
Developer tools & data|Algolia|greenhouse|algolia
Developer tools & data|Apollo GraphQL|ashby|apollo-graphql
Developer tools & data|Buildkite|greenhouse|buildkite
Developer tools & data|CircleCI|greenhouse|circleci
Developer tools & data|Clerk|ashby|clerk
Developer tools & data|ClickUp|ashby|clickup
Developer tools & data|CodeRabbit|ashby|coderabbit
Developer tools & data|Contentful|greenhouse|contentful
Developer tools & data|Cribl|greenhouse|cribl
Developer tools & data|Hex|ashby|hex
Developer tools & data|Hightouch|ashby|hightouch
Developer tools & data|Honeycomb|greenhouse|honeycomb
Developer tools & data|Inngest|ashby|inngest
Developer tools & data|Kong|ashby|kong
Developer tools & data|LaunchDarkly|greenhouse|launchdarkly
Developer tools & data|LiveKit|ashby|livekit
Developer tools & data|Materialize|ashby|materialize
Developer tools & data|Mintlify|ashby|mintlify
Developer tools & data|Mixpanel|greenhouse|mixpanel
Developer tools & data|MotherDuck|ashby|motherduck
Developer tools & data|Mux|ashby|mux
Developer tools & data|n8n|ashby|n8n
Developer tools & data|Netlify|greenhouse|netlify
Developer tools & data|Postman|workday|postman|wd108|careers
Developer tools & data|Prefect|ashby|prefect
Developer tools & data|Railway|ashby|railway
Developer tools & data|Render|ashby|render
Developer tools & data|Resend|ashby|resend
Developer tools & data|Sanity|ashby|sanity
Developer tools & data|Sentry|ashby|sentry
Developer tools & data|Sigma Computing|greenhouse|sigmacomputing
Developer tools & data|SingleStore|greenhouse|singlestore
Developer tools & data|Speakeasy|ashby|speakeasy
Developer tools & data|StreamNative|greenhouse|streamnative
Developer tools & data|Tines|greenhouse|tines
Developer tools & data|WorkOS|ashby|workos
Developer tools & data|Zed Industries|ashby|zed
Security|Apiiro|greenhouse|apiiro
Security|Arctic Wolf|workday|arcticwolf|wd1|External
Security|Axonius|greenhouse|axonius
Security|Bitwarden|greenhouse|bitwarden
Security|Chainguard|greenhouse|chainguard
Security|Coalition|greenhouse|coalition
Security|Doppler|ashby|doppler
Security|Endor Labs|greenhouse|endorlabs
Security|Expel|greenhouse|expel
Security|Huntress|greenhouse|huntress
Security|Illumio|ashby|illumio
Security|Island|greenhouse|island
Security|Keeper Security|greenhouse|keepersecurity
Security|Netskope|greenhouse|netskope
Security|Nightfall AI|ashby|nightfall-ai
Security|Oligo|ashby|oligo
Security|Orca Security|greenhouse|orcasecurity
Security|Secureframe|lever|secureframe
Security|Semgrep|ashby|semgrep
Security|Socket|ashby|socket
Security|Sysdig|lever|sysdig
Security|Thoropass|greenhouse|thoropass
Security|Torq|greenhouse|torq
Fintech & crypto|Acorns|ashby|acorns
Fintech & crypto|Airwallex|ashby|airwallex
Fintech & crypto|Alchemy|ashby|alchemy
Fintech & crypto|Alloy|greenhouse|alloy
Fintech & crypto|Alpaca|greenhouse|alpaca
Fintech & crypto|AngelList|lever|angellist
Fintech & crypto|Betterment|greenhouse|betterment
Fintech & crypto|Capchase|ashby|capchase
Fintech & crypto|Consensys|greenhouse|consensys
Fintech & crypto|Fireblocks|greenhouse|fireblocks
Fintech & crypto|Highnote|greenhouse|highnote
Fintech & crypto|Kalshi|ashby|kalshi
Fintech & crypto|Lithic|greenhouse|lithic
Fintech & crypto|Middesk|ashby|middesk
Fintech & crypto|Modern Treasury|ashby|moderntreasury
Fintech & crypto|Paxos|ashby|paxos
Fintech & crypto|Persona|ashby|persona
Fintech & crypto|Phantom|ashby|phantom
Fintech & crypto|Polymarket|ashby|polymarket
Fintech & crypto|Ramp|ashby|ramp
Fintech & crypto|Rho|ashby|rho
Fintech & crypto|Ripple|greenhouse|ripple
Fintech & crypto|Sardine|ashby|sardine
Fintech & crypto|Socure|ashby|socure
Fintech & crypto|Synctera|ashby|synctera
Fintech & crypto|Treasury Prime|greenhouse|treasuryprime
Fintech & crypto|Uniswap Labs|ashby|uniswap
Fintech & crypto|Wealthsimple|ashby|wealthsimple
Health|Calm|greenhouse|calm
Health|Cityblock Health|workday|cityblockhealth|wd1|CityblockExternalCareerSite
Health|Color Health|ashby|color-health
Health|Commure|ashby|commure
Health|Crossover Health|workday|crossoverhealth|wd1|Careers
Health|Devoted Health|workday|devoted|wd1|Devoted
Health|Freenome|greenhouse|freenome
Health|Garner Health|greenhouse|garnerhealth
Health|Generate Biomedicines|greenhouse|generatebiomedicines
Health|Grow Therapy|ashby|grow-therapy
Health|Inceptive|greenhouse|inceptive
Health|Included Health|lever|includedhealth
Health|Infinitus|ashby|infinitus
Health|Insitro|ashby|insitro
Health|Isomorphic Labs|greenhouse|isomorphiclabs
Health|Komodo Health|greenhouse|komodohealth
Health|Maven Clinic|greenhouse|mavenclinic
Health|Nabla|ashby|nabla
Health|Nomi Health|lever|nomihealth
Health|Omada Health|greenhouse|omadahealth
Health|Pager Health|greenhouse|pagerhealth
Health|Rula|ashby|rula
Health|SonderMind|ashby|sondermind
Health|Suki|greenhouse|suki
Health|Sword Health|greenhouse|swordhealth
Health|Virta Health|ashby|virtahealth
Health|Xaira Therapeutics|greenhouse|xairatherapeutics
Health|Zocdoc|greenhouse|zocdoc
Robotics, defense & space|1X|ashby|1x
Robotics, defense & space|Agility Robotics|greenhouse|agilityrobotics
Robotics, defense & space|Apptronik|greenhouse|apptronik
Robotics, defense & space|Astranis|greenhouse|astranis
Robotics, defense & space|Bedrock Robotics|ashby|bedrock-robotics
Robotics, defense & space|Bright Machines|lever|brightmachines
Robotics, defense & space|Chaos Industries|greenhouse|chaosindustries
Robotics, defense & space|Dexterity|lever|dexterity
Robotics, defense & space|Divergent|greenhouse|divergent
Robotics, defense & space|Epirus|greenhouse|epirus
Robotics, defense & space|Figure AI|greenhouse|figureai
Robotics, defense & space|Hermeus|lever|hermeus
Robotics, defense & space|Impulse Space|ashby|impulse
Robotics, defense & space|Kodiak Robotics|greenhouse|kodiak
Robotics, defense & space|Mach Industries|greenhouse|machindustries
Robotics, defense & space|Machina Labs|ashby|machina-labs
Robotics, defense & space|Muon Space|greenhouse|muonspace
Robotics, defense & space|Path Robotics|greenhouse|pathrobotics
Robotics, defense & space|Relativity Space|greenhouse|relativity
Robotics, defense & space|Saronic|ashby|saronic
Robotics, defense & space|Shield AI|ashby|shield
Robotics, defense & space|Skydio|ashby|skydio
Robotics, defense & space|Vannevar Labs|greenhouse|vannevarlabs
Robotics, defense & space|Varda Space|greenhouse|vardaspace
Robotics, defense & space|Vast|greenhouse|vast
Robotics, defense & space|Wayve|ashby|wayve
Climate & energy|Antora Energy|greenhouse|antora
Climate & energy|Aurora Solar|ashby|aurorasolar
Climate & energy|Fervo Energy|greenhouse|fervoenergy
Climate & energy|Form Energy|ashby|formenergy
Climate & energy|Helion|ashby|helion
Climate & energy|Kairos Power|greenhouse|kairospower
Climate & energy|Redwood Materials|greenhouse|redwoodmaterials
Climate & energy|Rondo Energy|greenhouse|rondoenergy
Climate & energy|Span|ashby|span
Climate & energy|Watershed|ashby|watershed
Climate & energy|X-energy|workday|xenergy|wd5|X-energyUS
Work & HR tech|15Five|lever|15five
Work & HR tech|Apollo.io|greenhouse|apolloio
Work & HR tech|Ashby|ashby|ashby
Work & HR tech|Attio|ashby|attio
Work & HR tech|Checkr|greenhouse|checkr
Work & HR tech|Culture Amp|greenhouse|cultureamp
Work & HR tech|Fieldwire|greenhouse|fieldwire
Work & HR tech|Instawork|greenhouse|instawork
Work & HR tech|Jobber|ashby|jobber
Work & HR tech|Justworks|greenhouse|justworks
Work & HR tech|Mural|ashby|mural
Work & HR tech|Outreach|lever|outreach
Work & HR tech|Oyster|ashby|oyster
Work & HR tech|People.ai|lever|people-ai
Work & HR tech|Pylon|ashby|pylon
Work & HR tech|Shiftsmart|ashby|shiftsmart
Work & HR tech|Warp (payroll)|ashby|warp
Consumer & commerce|Attentive|greenhouse|attentive
Consumer & commerce|Brilliant|lever|brilliant
Consumer & commerce|Cameo|greenhouse|cameo
Consumer & commerce|Glossier|greenhouse|glossier
Consumer & commerce|Gorgias|ashby|gorgias
Consumer & commerce|Handshake|ashby|handshake
Consumer & commerce|Hopper|ashby|hopper
Consumer & commerce|Oura|greenhouse|oura
Consumer & commerce|Outschool|ashby|outschool
Consumer & commerce|Pacaso|greenhouse|pacaso
Consumer & commerce|Partiful|ashby|partiful
Consumer & commerce|Patreon|ashby|patreon
Consumer & commerce|Postscript|greenhouse|postscript
Consumer & commerce|Roofstock|greenhouse|roofstock
Consumer & commerce|Strava|ashby|strava
Consumer & commerce|Substack|ashby|substack
Consumer & commerce|Whoop|ashby|whoop
Consumer & commerce|Yotpo|greenhouse|yotpo
"""

STARTUPS: list[dict] = [
    {"category": c, "company": n, "kind": k, "identifier": i, "via": "direct"}
    for c, n, k, i in (line.split("|", 3) for line in _STARTUPS.strip().splitlines())
]
