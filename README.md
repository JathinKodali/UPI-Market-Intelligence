# UPI Market Intelligence

A Power BI dashboard that analyses India's Unified Payments Interface (UPI) as a business market: how fast it is growing, who controls it, where people spend, what the new 0.4% merchant fee (MDR) will earn, which banks fail their customers, and which states drive usage.

All data is official NPCI statistics, collected from npci.org.in (Product Statistics and Ecosystem Statistics) up to **August 2026**.

## Open the dashboard

1. Keep this folder somewhere with a **short path** (for example `Documents\UPI Market Intelligence`). Power BI Desktop cannot open projects whose file paths exceed 260 characters.
2. Run `python tools/build_pbip.py` once. It regenerates the project and points the `DataFolder` parameter at this folder's `data` subfolder.
3. Double-click **`UPI Market Intelligence.pbip`**. It opens in Power BI Desktop (July 2026 or later).
4. Click **Home > Refresh** to load the CSV data. The visuals stay empty until the first refresh.

If you move the folder later, either rerun step 2 or change the path in **Transform data > Edit parameters > DataFolder** (the path must end with `\`).

## Report pages

| Page | Business question | Main visuals |
|---|---|---|
| Market Overview | How big is UPI and how fast is it growing? | KPI cards, monthly trend since 2016, fiscal-year totals, average payment size |
| App Competition | Who controls UPI, and can the leaders meet NPCI's 30% cap? | 100% stacked market share, share by app, growth by app, HHI concentration |
| Merchant Payments | Where do people spend? | P2M share trend, top 15 merchant categories, value by sector, category table |
| MDR Simulator | What is the new 0.4% merchant fee worth, and who earns it? | What-if slicers, revenue per month and year, split by party and by app |
| Bank Reliability | Which banks fail their customers, and why? | Approval rate by bank, size vs reliability scatter, decline trend by bank type |
| State-wise Adoption | Which states drive UPI? | Top 15 states, regions, average payment by state, state scorecard |
| About the Data | Sources, method, definitions, limitations | Text |

The **Month** slicer (top right, synced across pages) changes every KPI, ranking and headline. Trend charts always show full history.

## Key findings (August 2026)

- UPI processed **24.51 bn** transactions worth **₹29.82 lakh crore**, **+22.5%** on August 2025 (791 mn a day).
- The average payment fell to **₹1,217** from ₹1,489 three years earlier: UPI is becoming an everyday small-payments network.
- **PhonePe (45.9%) and Google Pay (32.4%)** handle 78.3% of UPI volume. HHI is 3,250 (highly concentrated). To meet NPCI's 30% cap by 31 Dec 2026, PhonePe would have to shift about **3.9 bn payments a month**.
- Merchant payments are **63%** of transactions but only **30%** of value (₹577 per shop payment vs ₹2,319 person-to-person).
- A 0.4% MDR on the ~67% of merchant value above ₹2,000 is worth about **₹2,400 crore a month (~₹28,800 crore a year)** before the ₹300 cap and ₹5 flat-fee sectors.
- **89.0%** of payment attempts from the top 20 banks succeeded. Business declines (wrong PIN, limits, balance) are 10.9%; technical failures only 0.18%. Payments banks (Airtel, Fino, India Post) have the lowest approval rates.
- **Maharashtra** has 17.5% of located UPI volume; the top 5 states have 51%. 44% of transactions carry no state tag.

## Data

| File | Source (NPCI) | Coverage |
|---|---|---|
| `upi_monthly_totals.csv` | Product Statistics > UPI | Apr 2016 - Aug 2026 |
| `upi_p2p_p2m.csv` | Ecosystem Statistics > P2P and P2M Transactions | Apr 2020 - Aug 2026 |
| `upi_apps.csv` | Ecosystem Statistics > UPI Applications (top 16 apps + Others) | Apr 2023 - Aug 2026 |
| `upi_merchant_category.csv` | Ecosystem Statistics > Merchant Category Classification | Apr 2025 - Aug 2026 |
| `upi_state.csv` | Ecosystem Statistics > UPI Statewise Statistics (districts summed to states) | Apr 2025 - Aug 2026 |
| `upi_bank_performance.csv` | Ecosystem Statistics > Top 50 Member Performance > Remitter (top 20 banks) | Apr 2025 - Aug 2026 |
| `dim_*.csv` | Lookup tables written for this project (clean names, groups, regions, bank types) | - |

Volume is in millions of transactions; value is in rupees crore (1 lakh crore = ₹1 trillion).

MDR inputs: NPCI circular of 15 Sep 2026 (0.4% on merchant payments above ₹2,000, capped at ₹300, from 15 Oct 2026). The revenue split (issuer 40%, acquirer 30%, app 20%, app's bank 10%) and the 67% high-value share come from financial press coverage of that circular, so the simulator lets you change them.

## Model

- **Power Query:** 10 CSV queries, typed with an en-US culture; P2P/P2M unpivoted to one row per payment type; bank names standardised with an upper-case key; month text converted to dates.
- **Star schema:** six fact tables (monthly totals, P2P/P2M, apps, merchant categories, states, banks) share a monthly `DimDate` with the Indian fiscal year (April-March). Dimensions: `DimApp`, `DimBank`, `DimState`, `DimMerchantCategory`. Four calculated what-if tables drive the MDR page.
- **DAX:** 101 measures in `_Measures`, grouped by page: selected-month KPIs, same-month-last-year growth, market share, HHI, Top-N ranking, volume-weighted decline rates, what-if revenue and dynamic headline text.

## Machine learning forecast

`tools/train_forecast.py` trains a Ridge regression model on lagged monthly UPI
volumes, trend and calendar features. It uses a chronological 12-month holdout
and writes its fitted parameters, test results and 12-month forecast to
`output/ml_forecast/`. See [the method and measured results](docs/ML_FORECAST.md)
for the training protocol, limitations and reproduction commands. This Python
forecast is separate from the report's original DAX growth scenario.

## Rebuilding the Power BI report

`tools/build_pbip.py` generates the whole project (TMDL model + PBIR report) from code. Edit measures or visuals there and rerun it. To add a new month, append the NPCI figures to the CSVs, rerun the script, and refresh in Power BI.

## Limitations

- NPCI publishes monthly aggregates, not transactions, so this is market-level analysis.
- App data groups the long tail into "Others"; bank data covers the 20 largest sending banks.
- About 44% of transactions have no state tag, so state shares use located volume only.
- MDR revenue is an estimate: NPCI does not publish merchant value by ticket size.
- The 30% cap deadline (31 Dec 2026) is as last extended by NPCI in December 2024.
