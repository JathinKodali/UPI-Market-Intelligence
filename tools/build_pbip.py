"""Generate the UPI Market Intelligence Power BI project (PBIP: TMDL model + PBIR report).

Run from anywhere:  python tools/build_pbip.py

The NPCI CSV files in ./data are compressed and embedded in the Power Query source steps,
so the report refreshes on any computer without file paths. To add a month, edit the CSVs,
rerun this script, then open the .pbip and click Refresh.
"""
import base64
import json
import shutil
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NAME = "UPI Market Intelligence"
SM = ROOT / f"{NAME}.SemanticModel"
RP = ROOT / f"{NAME}.Report"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
V_REPORT, V_PAGE, V_VISUAL = "3.1.0", "2.0.0", "2.5.0"

NS = uuid.UUID("6a1f0c52-9d3e-4b8a-a1f7-2c5e8d9b0f11")

# Colours. Categorical slots follow a colour-blind-validated order; status colours are reserved for good/bad.
NAVY, INK, INK2, MUTED = "#1E2A5A", "#1E2A5A", "#5B6475", "#8A93A6"
PAGE_BG, TILE_BORDER, STRIP_BG, WHITE = "#F4F6FB", "#E3E7F0", "#EAEEF9", "#FFFFFF"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#4A3AA7", "#E34948")
GOOD, BAD, GOOD_TEXT, NEUTRAL_TEXT = "#0CA30C", "#D03B3B", "#006300", "#5B6475"


def guid(key):
    """Stable GUID so rebuilds do not churn lineage tags."""
    return str(uuid.uuid5(NS, key))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# ==============================================================================================
# Semantic model (TMDL)
# ==============================================================================================

def q(name):
    if name.replace("_", "").isalnum() and not name[0].isdigit():
        return name
    return "'" + name.replace("'", "''") + "'"


def indent(text, level):
    pad = "\t" * level
    return "\n".join((pad + line) if line.strip() else "" for line in text.strip("\n").split("\n"))


MONTHS_SHORT = '{"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}'
MONTHS_LONG = ('{"January", "February", "March", "April", "May", "June", "July", "August", '
               '"September", "October", "November", "December"}')


def embedded_csv(file, ncols):
    """Power Query expression that rebuilds the CSV from compressed text stored in the model."""
    raw = (DATA / file).read_bytes()
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    blob = base64.b64encode(comp.compress(raw) + comp.flush()).decode("ascii")
    return (f'Csv.Document(Binary.Decompress(Binary.FromText("{blob}", BinaryEncoding.Base64), Compression.Deflate), '
            f'[Delimiter = ",", Columns = {ncols}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv])')


def m_query(file, ncols, steps):
    head = [
        f"// Source: data/{file} (official NPCI statistics), embedded so the report refreshes on any computer",
        "let",
    ]
    body = [f"    Source = {embedded_csv(file, ncols)}",
            "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])"] + ["    " + s for s in steps]
    return "\n".join(head) + "\n" + ",\n".join(body) + "\nin\n    Result"


def monthly_steps(types, extra_steps, renames, keep):
    type_list = ", ".join(f'{{"{c}", {t}}}' for c, t in types)
    rename_list = ", ".join(f'{{"{a}", "{b}"}}' for a, b in renames)
    keep_list = ", ".join(f'"{c}"' for c in keep)
    steps = [
        f'Typed = Table.TransformColumnTypes(Promoted, {{{{"year", Int64.Type}}, {{"month", type text}}, {type_list}}}, "en-US")',
        f"MonthNames = {MONTHS_SHORT}",
        'AddDate = Table.AddColumn(Typed, "Date", each #date([year], List.PositionOf(MonthNames, [month]) + 1, 1), type date)',
    ]
    prev = "AddDate"
    for name, step in extra_steps:
        steps.append(f"{name} = {step.replace('{prev}', prev)}")
        prev = name
    steps.append(f"Renamed = Table.RenameColumns({prev}, {{{rename_list}}})")
    steps.append(f"Result = Table.SelectColumns(Renamed, {{{keep_list}}})")
    return steps


def dim_steps(types, renames):
    type_list = ", ".join(f'{{"{c}", {t}}}' for c, t in types)
    rename_list = ", ".join(f'{{"{a}", "{b}"}}' for a, b in renames)
    return [f'Typed = Table.TransformColumnTypes(Promoted, {{{type_list}}}, "en-US")',
            f"Result = Table.RenameColumns(Typed, {{{rename_list}}})"]


def col(name, dtype, source=None, fmt=None, summarize="none", hidden=False, key=False,
        sort_by=None, inferred=False, category=None, description=None):
    return dict(name=name, dtype=dtype, source=source if source is not None else name, fmt=fmt,
                summarize=summarize, hidden=hidden, key=key, sort_by=sort_by,
                inferred=inferred, category=category, description=description)


def table_tmdl(name, columns, partition_kind, partition_source, measures=(), hidden=False,
               data_category=None, description=None):
    out = []
    if description:
        out.append(f"/// {description}")
    out.append(f"table {q(name)}")
    if hidden:
        out.append("\tisHidden")
    if data_category:
        out.append(f"\tdataCategory: {data_category}")
    out.append(f"\tlineageTag: {guid('table:' + name)}")
    out.append("")
    for mname, expr, fmt, folder, desc in measures:
        if desc:
            out.append(f"\t/// {desc}")
        expr = expr.strip("\n")
        if "\n" in expr:
            out.append(f"\tmeasure {q(mname)} =")
            out.append(indent(expr, 3))
        else:
            out.append(f"\tmeasure {q(mname)} = {expr.strip()}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        if folder:
            out.append(f"\t\tdisplayFolder: {folder}")
        out.append(f"\t\tlineageTag: {guid('measure:' + name + ':' + mname)}")
        out.append("")
    for c in columns:
        if c["description"]:
            out.append(f"\t/// {c['description']}")
        out.append(f"\tcolumn {q(c['name'])}")
        out.append(f"\t\tdataType: {c['dtype']}")
        if c["hidden"]:
            out.append("\t\tisHidden")
        if c["key"]:
            out.append("\t\tisKey")
        if c["fmt"]:
            out.append(f"\t\tformatString: {c['fmt']}")
        if c["category"]:
            out.append(f"\t\tdataCategory: {c['category']}")
        out.append(f"\t\tlineageTag: {guid('column:' + name + ':' + c['name'])}")
        out.append(f"\t\tsummarizeBy: {c['summarize']}")
        if c["inferred"]:
            out.append("\t\tisNameInferred")
        out.append(f"\t\tsourceColumn: {c['source']}")
        if c["sort_by"]:
            out.append(f"\t\tsortByColumn: {q(c['sort_by'])}")
        out.append("")
        out.append("\t\tannotation SummarizationSetBy = Automatic")
        out.append("")
    out.append(f"\tpartition {q(name)} = {partition_kind}")
    out.append("\t\tmode: import")
    out.append("\t\tsource =")
    out.append(indent(partition_source, 4))
    out.append("")
    out.append("\tannotation PBI_ResultType = Table")
    out.append("")
    return "\n".join(out)


def month_measure(inner):
    """Value for the month picked in the Month slicer (latest month when nothing is picked)."""
    return f"""
VAR _m = [Selected Month Index]
RETURN
    CALCULATE ( {inner}, REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m )
"""


def ly_measure(inner):
    """Value for the same month one year earlier."""
    return f"""
VAR _m = [Selected Month Index] - 12
RETURN
    CALCULATE ( {inner}, REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m )
"""


def growth_sub(cur, ly, fmt="0.0%"):
    """KPI subtitle text such as '▲ 22.5% vs Aug 2025'."""
    return f"""
VAR _cur = {cur}
VAR _ly = {ly}
RETURN
    IF (
        ISBLANK ( _cur ) || ISBLANK ( _ly ) || _ly = 0,
        "No data a year earlier",
        VAR _g = DIVIDE ( _cur - _ly, _ly )
        RETURN IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "{fmt}" ) & " vs " & [Same Month LY Label]
    )
"""


def pts_sub(cur, ly, decimals="0.0"):
    """KPI subtitle text for a change in percentage points, such as '▼ 0.9 pts vs Aug 2025'."""
    return f"""
VAR _cur = {cur}
VAR _ly = {ly}
RETURN
    IF (
        ISBLANK ( _cur ) || ISBLANK ( _ly ),
        "No data a year earlier",
        VAR _d = ( _cur - _ly ) * 100
        RETURN IF ( _d >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _d ), "{decimals}" ) & " pts vs " & [Same Month LY Label]
    )
"""


def sign_color(expr, up_is_good=True):
    good, bad = (GOOD_TEXT, BAD) if up_is_good else (BAD, GOOD_TEXT)
    return f'VAR _v = {expr} RETURN IF ( ISBLANK ( _v ), "{NEUTRAL_TEXT}", IF ( _v >= 0, "{good}", "{bad}" ) )'


PCT, PCT2, GROWTH, INT, DEC2, RUPEE = "0.0%", "0.00%", "+0.0%;-0.0%;0.0%", "#,0", "#,0.00", "₹#,0"

F_BASE, F_MKT, F_APP, F_MER, F_MDR, F_BNK, F_GEO, F_TXT, F_CLR = (
    "0 Helpers", "1 Market", "2 Apps", "3 Merchant payments", "4 MDR simulator", "5 Banks", "6 States",
    "7 Text for the report", "8 Colours for conditional formatting")

MEASURES = [
    # ---------------------------------------------------------------- helpers
    ("Selected Month Index", "MAX ( DimDate[Month Index] )", "0", F_BASE,
     "Month picked in the Month slicer. With nothing picked this is the latest month in the data."),
    ("Selected Month", 'FORMAT ( MAX ( DimDate[Date] ), "mmmm yyyy" )', None, F_BASE, None),
    ("Selected Month Short", 'FORMAT ( MAX ( DimDate[Date] ), "mmm yyyy" )', None, F_BASE, None),
    ("Same Month LY Label", 'FORMAT ( EDATE ( MAX ( DimDate[Date] ), -12 ), "mmm yyyy" )', None, F_BASE, None),
    ("Latest Data Month", 'FORMAT ( CALCULATE ( MAX ( FactUPIMonthly[Date] ), REMOVEFILTERS ( DimDate ) ), "mmmm yyyy" )',
     None, F_BASE, None),
    ("Page Subtitle", '"Official NPCI statistics   |   Showing " & [Selected Month] & "   |   Data up to " & [Latest Data Month]',
     None, F_BASE, None),

    # ---------------------------------------------------------------- market
    ("UPI Volume (Mn)", "SUM ( FactUPIMonthly[Volume Mn] )", INT, F_MKT, "Number of UPI transactions, in millions."),
    ("UPI Value (Cr)", "SUM ( FactUPIMonthly[Value Cr] )", INT, F_MKT, "Value of UPI transactions, in rupees crore."),
    ("UPI Volume (Bn)", "DIVIDE ( [UPI Volume (Mn)], 1000 )", DEC2, F_MKT, None),
    ("UPI Value (Lakh Cr)", "DIVIDE ( [UPI Value (Cr)], 100000 )", DEC2, F_MKT, None),
    ("UPI Volume since FY19 (Bn)", "IF ( MAX ( DimDate[FY Start Year] ) >= 2018, [UPI Volume (Bn)] )", DEC2, F_MKT,
     "Hides the launch years so the fiscal-year chart stays readable."),
    ("Avg Ticket Size (₹)", "DIVIDE ( [UPI Value (Cr)], [UPI Volume (Mn)] ) * 10", RUPEE, F_MKT,
     "Average rupees per transaction. Crore / million x 10 = rupees."),
    ("Avg Ticket Size since FY20 (₹)", "IF ( MAX ( DimDate[Date] ) >= DATE ( 2019, 4, 1 ), [Avg Ticket Size (₹)] )", RUPEE,
     F_MKT, "Hides the launch years (2016-2019) when tiny volumes make the average meaningless."),
    ("Volume Bn (Month)", month_measure("[UPI Volume (Bn)]"), DEC2, F_MKT, None),
    ("Volume Bn (Same Month LY)", ly_measure("[UPI Volume (Bn)]"), DEC2, F_MKT, None),
    ("Volume YoY % (Month)", "DIVIDE ( [Volume Bn (Month)] - [Volume Bn (Same Month LY)], [Volume Bn (Same Month LY)] )",
     GROWTH, F_MKT, None),
    ("Value Lakh Cr (Month)", month_measure("[UPI Value (Lakh Cr)]"), DEC2, F_MKT, None),
    ("Value Lakh Cr (Same Month LY)", ly_measure("[UPI Value (Lakh Cr)]"), DEC2, F_MKT, None),
    ("Value YoY % (Month)", "DIVIDE ( [Value Lakh Cr (Month)] - [Value Lakh Cr (Same Month LY)], [Value Lakh Cr (Same Month LY)] )",
     GROWTH, F_MKT, None),
    ("Avg Ticket ₹ (Month)", month_measure("[Avg Ticket Size (₹)]"), RUPEE, F_MKT, None),
    ("Avg Ticket ₹ (3 Years Earlier)", """
VAR _m = [Selected Month Index] - 36
RETURN
    CALCULATE ( [Avg Ticket Size (₹)], REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m )
""", RUPEE, F_MKT, None),
    ("Daily Transactions Mn (Month)", """
VAR _m = [Selected Month Index]
VAR _d = CALCULATE ( MAX ( DimDate[Date] ), REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m )
RETURN
    DIVIDE ( [Volume Bn (Month)] * 1000, DAY ( EOMONTH ( _d, 0 ) ) )
""", INT, F_MKT, None),
    ("Banks Live (Month)", month_measure("SUM ( FactUPIMonthly[Banks Live] )"), INT, F_MKT, None),
    ("UPI Volume YoY %", """
VAR _m = MAX ( DimDate[Month Index] )
VAR _cur = [UPI Volume (Mn)]
VAR _ly = CALCULATE ( [UPI Volume (Mn)], REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m - 12 )
RETURN
    IF ( HASONEVALUE ( DimDate[Month Index] ) && NOT ISBLANK ( _cur ) && _ly > 0, DIVIDE ( _cur - _ly, _ly ) )
""", GROWTH, F_MKT, None),
    ("Months to 30 Bn", """
VAR _v = [Volume Bn (Month)]
VAR _g = [Volume YoY % (Month)]
RETURN
    IF (
        _v >= 30, 0,
        IF ( _g > 0 && _v > 0, ROUNDUP ( DIVIDE ( LN ( 30 / _v ), LN ( 1 + _g ) / 12 ), 0 ) )
    )
""", "0", F_MKT, "Months until 30 bn transactions a month if the latest year-on-year growth rate continues (compound, no seasonality)."),
    ("30 Bn Month Projection", """
VAR _n = [Months to 30 Bn]
RETURN
    IF ( ISBLANK ( _n ), "n/a", IF ( _n = 0, "Reached", FORMAT ( EDATE ( MAX ( DimDate[Date] ), _n ), "mmm yyyy" ) ) )
""", None, F_MKT, None),

    # ---------------------------------------------------------------- apps
    ("App Volume (Mn)", "SUM ( FactAppMonthly[Volume Mn] )", INT, F_APP, None),
    ("App Value (Cr)", "SUM ( FactAppMonthly[Value Cr] )", INT, F_APP, None),
    ("App Market Share %", "DIVIDE ( [App Volume (Mn)], CALCULATE ( [App Volume (Mn)], REMOVEFILTERS ( DimApp ) ) )",
     PCT, F_APP, "Share of UPI transactions (volume) handled by the app."),
    ("App Volume Mn (Month)", month_measure("[App Volume (Mn)]"), INT, F_APP, None),
    ("App Volume Mn (Same Month LY)", ly_measure("[App Volume (Mn)]"), INT, F_APP, None),
    ("App Share % (Month)", month_measure("[App Market Share %]"), PCT, F_APP, None),
    ("App Share % (Same Month LY)", ly_measure("[App Market Share %]"), PCT, F_APP, None),
    ("App Volume YoY % (Month)", """
VAR _cur = [App Volume Mn (Month)]
VAR _ly = [App Volume Mn (Same Month LY)]
RETURN
    IF ( _ly > 1, DIVIDE ( _cur - _ly, _ly ) )
""", GROWTH, F_APP, "Growth vs the same month last year. Blank for apps that were not live a year ago."),
    ("PhonePe Share % (Month)", 'CALCULATE ( [App Share % (Month)], DimApp[App] = "PhonePe" )', PCT, F_APP, None),
    ("Google Pay Share % (Month)", 'CALCULATE ( [App Share % (Month)], DimApp[App] = "Google Pay" )', PCT, F_APP, None),
    ("Top 2 Apps Share % (Month)", 'CALCULATE ( [App Share % (Month)], DimApp[App] IN { "PhonePe", "Google Pay" } )', PCT, F_APP, None),
    ("Top 2 Apps Share % (Same Month LY)", 'CALCULATE ( [App Share % (Same Month LY)], DimApp[App] IN { "PhonePe", "Google Pay" } )',
     PCT, F_APP, None),
    ("Market Concentration HHI (Month)", """
VAR _m = [Selected Month Index]
VAR _total =
    CALCULATE ( [App Volume (Mn)], REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m, REMOVEFILTERS ( DimApp ) )
RETURN
    IF (
        _total > 0,
        SUMX (
            ALL ( DimApp[App] ),
            VAR _s = DIVIDE ( CALCULATE ( [App Volume (Mn)], REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m ), _total ) * 100
            RETURN _s * _s
        )
    )
""", INT, F_APP, "Herfindahl-Hirschman Index: sum of squared market shares. Above 2,500 = highly concentrated."),
    ("Apps Above 30% Cap (Month)", "COUNTROWS ( FILTER ( ALL ( DimApp[App] ), [App Share % (Month)] > 0.3 ) )", "0", F_APP, None),
    ("Gap to 30% Cap (pts)", "IF ( NOT ISBLANK ( [App Share % (Month)] ), ( [App Share % (Month)] - 0.3 ) * 100 )",
     "+0.0;-0.0;0.0", F_APP, "Percentage points above (+) or below (-) NPCI's 30% volume cap."),
    ("Days to Cap Deadline", "MAX ( 0, DATEDIFF ( TODAY (), DATE ( 2026, 12, 31 ), DAY ) )", "0", F_APP,
     "Days until 31 Dec 2026, the 30% market-share cap deadline as last extended by NPCI (Dec 2024)."),
    ("Volume Above Cap Mn (Month)", """
VAR _share = [PhonePe Share % (Month)]
VAR _total = CALCULATE ( [App Volume Mn (Month)], REMOVEFILTERS ( DimApp ) )
RETURN
    MAX ( 0, _share - 0.3 ) * _total
""", INT, F_APP, "Monthly transactions PhonePe would have to move to other apps to get down to 30%."),
    ("Fastest Growing App (Month)", """
VAR _t =
    TOPN (
        1,
        FILTER ( ALL ( DimApp[App] ), DimApp[App] <> "Others" && [App Volume Mn (Same Month LY)] >= 50 ),
        [App Volume YoY % (Month)], DESC
    )
RETURN
    IF ( COUNTROWS ( _t ) > 0, MAXX ( _t, DimApp[App] ) & " (" & FORMAT ( MAXX ( _t, [App Volume YoY % (Month)] ), "+0%" ) & ")" )
""", None, F_APP, "App with the highest year-on-year growth among apps that had at least 50 mn transactions a year earlier."),

    # ---------------------------------------------------------------- merchant payments
    ("P2x Volume (Mn)", "SUM ( FactP2PP2M[Volume Mn] )", INT, F_MER, None),
    ("P2x Value (Cr)", "SUM ( FactP2PP2M[Value Cr] )", INT, F_MER, None),
    ("P2M Volume (Mn)", 'CALCULATE ( [P2x Volume (Mn)], FactP2PP2M[Payment Type] = "P2M" )', INT, F_MER, None),
    ("P2M Value (Cr)", 'CALCULATE ( [P2x Value (Cr)], FactP2PP2M[Payment Type] = "P2M" )', INT, F_MER, None),
    ("P2P Volume (Mn)", 'CALCULATE ( [P2x Volume (Mn)], FactP2PP2M[Payment Type] = "P2P" )', INT, F_MER, None),
    ("P2P Value (Cr)", 'CALCULATE ( [P2x Value (Cr)], FactP2PP2M[Payment Type] = "P2P" )', INT, F_MER, None),
    ("P2M Share of Volume %", "DIVIDE ( [P2M Volume (Mn)], [P2M Volume (Mn)] + [P2P Volume (Mn)] )", PCT, F_MER,
     "Merchant (person-to-merchant) payments as a share of all UPI transactions."),
    ("P2M Share of Value %", "DIVIDE ( [P2M Value (Cr)], [P2M Value (Cr)] + [P2P Value (Cr)] )", PCT, F_MER, None),
    ("P2M Share of Volume % (Month)", month_measure("[P2M Share of Volume %]"), PCT, F_MER, None),
    ("P2M Share of Volume % (Same Month LY)", ly_measure("[P2M Share of Volume %]"), PCT, F_MER, None),
    ("P2M Share of Value % (Month)", month_measure("[P2M Share of Value %]"), PCT, F_MER, None),
    ("P2M Share of Value % (Same Month LY)", ly_measure("[P2M Share of Value %]"), PCT, F_MER, None),
    ("P2M Volume Bn (Month)", month_measure("[P2M Volume (Mn)] / 1000"), DEC2, F_MER, None),
    ("P2M Volume Bn (Same Month LY)", ly_measure("[P2M Volume (Mn)] / 1000"), DEC2, F_MER, None),
    ("Avg P2M Ticket ₹ (Month)", month_measure("DIVIDE ( [P2M Value (Cr)], [P2M Volume (Mn)] ) * 10"), RUPEE, F_MER, None),
    ("Avg P2M Ticket ₹ (Same Month LY)", ly_measure("DIVIDE ( [P2M Value (Cr)], [P2M Volume (Mn)] ) * 10"), RUPEE, F_MER, None),
    ("Avg P2P Ticket ₹ (Month)", month_measure("DIVIDE ( [P2P Value (Cr)], [P2P Volume (Mn)] ) * 10"), RUPEE, F_MER, None),
    ("Avg P2P Ticket ₹ (Same Month LY)", ly_measure("DIVIDE ( [P2P Value (Cr)], [P2P Volume (Mn)] ) * 10"), RUPEE, F_MER, None),
    ("Merchant Volume (Mn)", "SUM ( FactMerchantCategory[Volume Mn] )", INT, F_MER, None),
    ("Merchant Value (Cr)", "SUM ( FactMerchantCategory[Value Cr] )", INT, F_MER, None),
    ("Merchant Volume Mn (Month)", month_measure("[Merchant Volume (Mn)]"), INT, F_MER, None),
    ("Merchant Value Cr (Month)", month_measure("[Merchant Value (Cr)]"), INT, F_MER, None),
    ("Merchant Volume Mn (Same Month LY)", ly_measure("[Merchant Volume (Mn)]"), INT, F_MER, None),
    ("Merchant Volume YoY % (Month)", """
VAR _cur = [Merchant Volume Mn (Month)]
VAR _ly = [Merchant Volume Mn (Same Month LY)]
RETURN
    IF ( NOT ISBLANK ( _cur ) && _ly > 0, DIVIDE ( _cur - _ly, _ly ) )
""", GROWTH, F_MER, None),
    ("Category Avg Ticket ₹ (Month)", "DIVIDE ( [Merchant Value Cr (Month)], [Merchant Volume Mn (Month)] ) * 10", RUPEE, F_MER, None),
    ("Named Category Volume Mn (Month)",
     'CALCULATE ( [Merchant Volume Mn (Month)], KEEPFILTERS ( DimMerchantCategory[MCC] <> "OTH" ) )', INT, F_MER, None),
    ("Named Category Value Cr (Month)",
     'CALCULATE ( [Merchant Value Cr (Month)], KEEPFILTERS ( DimMerchantCategory[MCC] <> "OTH" ) )', INT, F_MER,
     "Merchant value excluding NPCI's 'all other categories' bucket."),
    ("Named Category Avg Ticket ₹ (Month)",
     'CALCULATE ( [Category Avg Ticket ₹ (Month)], KEEPFILTERS ( DimMerchantCategory[MCC] <> "OTH" ) )', RUPEE, F_MER, None),
    ("Named Category YoY % (Month)",
     'CALCULATE ( [Merchant Volume YoY % (Month)], KEEPFILTERS ( DimMerchantCategory[MCC] <> "OTH" ) )', GROWTH, F_MER, None),
    ("Top 15 Category Volume Mn (Month)", """
VAR _v = [Named Category Volume Mn (Month)]
VAR _r =
    RANKX (
        FILTER ( ALL ( DimMerchantCategory[Category] ), NOT ISBLANK ( [Named Category Volume Mn (Month)] ) ),
        [Named Category Volume Mn (Month)], , DESC
    )
RETURN
    IF ( NOT ISBLANK ( _v ) && _r <= 15, _v )
""", INT, F_MER, "Transactions for the 15 largest named merchant categories in the selected month."),
    ("Top Category (Month)", """
VAR _t =
    TOPN (
        1,
        FILTER ( ALL ( DimMerchantCategory[Category] ), NOT ISBLANK ( [Named Category Volume Mn (Month)] ) ),
        [Named Category Volume Mn (Month)], DESC
    )
RETURN
    MAXX ( _t, DimMerchantCategory[Category] )
""", None, F_MER, None),
    ("Top Category Volume Bn (Month)", """
VAR _t =
    TOPN (
        1,
        FILTER ( ALL ( DimMerchantCategory[Category] ), NOT ISBLANK ( [Named Category Volume Mn (Month)] ) ),
        [Named Category Volume Mn (Month)], DESC
    )
RETURN
    DIVIDE ( MAXX ( _t, [Named Category Volume Mn (Month)] ), 1000 )
""", DEC2, F_MER, None),

    # ---------------------------------------------------------------- MDR simulator
    ("MDR Rate (Selected)", "SELECTEDVALUE ( 'MDR Rate Options'[MDR Rate], 0.004 )", PCT2, F_MDR,
     "Fee rate chosen in the slicer. Defaults to NPCI's 0.40%."),
    ("High-Value Share (Selected)", "SELECTEDVALUE ( 'High Value Share Options'[Share], 0.67 )", "0%", F_MDR,
     "Share of merchant payment value in transactions above Rs 2,000. Defaults to the 67% reported for Aug 2026."),
    ("Cap Adjustment (Selected)", "SELECTEDVALUE ( 'Cap Adjustment Options'[Adjustment], 0 )", "0%", F_MDR,
     "Reduction for the Rs 300 cap, the Rs 5 flat fee in notified sectors and the small-merchant exemption."),
    ("P2M Value Cr (Month)", month_measure("[P2M Value (Cr)]"), INT, F_MDR, None),
    ("P2M Value Lakh Cr (Month)", "DIVIDE ( [P2M Value Cr (Month)], 100000 )", DEC2, F_MDR, None),
    ("MDR-Eligible Value Lakh Cr (Month)", "[P2M Value Lakh Cr (Month)] * [High-Value Share (Selected)]", DEC2, F_MDR, None),
    ("Est. MDR Revenue Cr (Month)",
     "[P2M Value Cr (Month)] * [High-Value Share (Selected)] * [MDR Rate (Selected)] * ( 1 - [Cap Adjustment (Selected)] )",
     INT, F_MDR, "Estimated merchant fee revenue for one month, in rupees crore."),
    ("Est. MDR Revenue Cr (Annualised)", "[Est. MDR Revenue Cr (Month)] * 12", INT, F_MDR, None),
    ("MDR Revenue by Party Cr", "[Est. MDR Revenue Cr (Month)] * SUM ( 'MDR Split'[Share] )", INT, F_MDR,
     "Revenue split using the sharing formula reported in the press (issuer 40%, acquirer 30%, app 20%, app's bank 10%)."),
    ("App Value Share % (Month)", """
VAR _m = [Selected Month Index]
RETURN
    DIVIDE (
        CALCULATE ( [App Value (Cr)], REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m ),
        CALCULATE ( [App Value (Cr)], REMOVEFILTERS ( DimDate ), DimDate[Month Index] = _m, REMOVEFILTERS ( DimApp ) )
    )
""", PCT, F_MDR, None),
    ("Est. App MDR Income Cr (Month)", "[Est. MDR Revenue Cr (Month)] * 0.2 * [App Value Share % (Month)]", DEC2, F_MDR,
     "Approximation: the apps' 20% pool split by each app's share of total UPI value."),

    # ---------------------------------------------------------------- banks
    ("Bank Volume (Mn)", "SUM ( FactBankPerformance[Volume Mn] )", INT, F_BNK, None),
    ("Approval Rate %",
     "DIVIDE ( SUMX ( FactBankPerformance, FactBankPerformance[Volume Mn] * FactBankPerformance[Approved %] ), [Bank Volume (Mn)] )",
     PCT2, F_BNK, "Volume-weighted share of payment attempts that succeeded."),
    ("Business Decline %",
     "DIVIDE ( SUMX ( FactBankPerformance, FactBankPerformance[Volume Mn] * FactBankPerformance[Business Decline %] ), [Bank Volume (Mn)] )",
     PCT2, F_BNK, "Declines caused by the customer or rules: wrong PIN, insufficient balance, limits."),
    ("Technical Decline %",
     "DIVIDE ( SUMX ( FactBankPerformance, FactBankPerformance[Volume Mn] * FactBankPerformance[Technical Decline %] ), [Bank Volume (Mn)] )",
     PCT2, F_BNK, "Declines caused by bank or NPCI system problems."),
    ("Bank Volume Mn (Month)", month_measure("[Bank Volume (Mn)]"), INT, F_BNK, None),
    ("Approval Rate % (Month)", month_measure("[Approval Rate %]"), PCT2, F_BNK, None),
    ("Approval Rate % (Same Month LY)", ly_measure("[Approval Rate %]"), PCT2, F_BNK, None),
    ("Business Decline % (Month)", month_measure("[Business Decline %]"), PCT2, F_BNK, None),
    ("Business Decline % (Same Month LY)", ly_measure("[Business Decline %]"), PCT2, F_BNK, None),
    ("Technical Decline % (Month)", month_measure("[Technical Decline %]"), PCT2, F_BNK, None),
    ("Technical Decline % (Same Month LY)", ly_measure("[Technical Decline %]"), PCT2, F_BNK, None),
    ("Failed Payments Mn (Month)", "[Bank Volume Mn (Month)] * ( 1 - [Approval Rate % (Month)] )", INT, F_BNK, None),
    ("Bottom 15 Approval Rate % (Month)", """
VAR _v = [Approval Rate % (Month)]
VAR _r =
    RANKX (
        FILTER ( ALL ( DimBank[Bank] ), NOT ISBLANK ( [Bank Volume Mn (Month)] ) ),
        [Approval Rate % (Month)], , ASC
    )
RETURN
    IF ( NOT ISBLANK ( _v ) && _r <= 15, _v )
""", PCT2, F_BNK, "Approval rate for the 15 banks with the lowest approval rate in the selected month."),
    ("Lowest Approval Bank Name (Month)", """
VAR _t =
    TOPN ( 1, FILTER ( ALL ( DimBank[Bank] ), NOT ISBLANK ( [Bank Volume Mn (Month)] ) ), [Approval Rate % (Month)], ASC )
RETURN
    MAXX ( _t, DimBank[Bank] )
""", None, F_BNK, None),
    ("Lowest Approval Rate % (Month)", """
VAR _t =
    TOPN ( 1, FILTER ( ALL ( DimBank[Bank] ), NOT ISBLANK ( [Bank Volume Mn (Month)] ) ), [Approval Rate % (Month)], ASC )
RETURN
    MAXX ( _t, [Approval Rate % (Month)] )
""", PCT, F_BNK, None),
    ("Highest Technical Decline Bank (Month)", """
VAR _t =
    TOPN ( 1, FILTER ( ALL ( DimBank[Bank] ), NOT ISBLANK ( [Bank Volume Mn (Month)] ) ), [Technical Decline % (Month)], DESC )
RETURN
    MAXX ( _t, DimBank[Bank] ) & " (" & FORMAT ( MAXX ( _t, [Technical Decline % (Month)] ), "0.00%" ) & ")"
""", None, F_BNK, None),

    # ---------------------------------------------------------------- states
    ("State Volume (Mn)", "SUM ( FactStateMonthly[Volume Mn] )", INT, F_GEO, None),
    ("State Value (Cr)", "SUM ( FactStateMonthly[Value Cr] )", INT, F_GEO, None),
    ("State Volume Mn (Month)", month_measure("[State Volume (Mn)]"), INT, F_GEO, None),
    ("State Value Cr (Month)", month_measure("[State Value (Cr)]"), INT, F_GEO, None),
    ("State Volume Mn (Same Month LY)", ly_measure("[State Volume (Mn)]"), INT, F_GEO, None),
    ("Located Volume Mn (Month)",
     'CALCULATE ( [State Volume Mn (Month)], KEEPFILTERS ( DimState[Classified] = "Yes" ) )', INT, F_GEO,
     "Transactions NPCI could assign to a state."),
    ("All Located Volume Mn (Month)",
     'CALCULATE ( [State Volume Mn (Month)], REMOVEFILTERS ( DimState ), DimState[Classified] = "Yes" )', INT, F_GEO, None),
    ("All Located Volume Mn (Same Month LY)",
     'CALCULATE ( [State Volume Mn (Same Month LY)], REMOVEFILTERS ( DimState ), DimState[Classified] = "Yes" )', INT, F_GEO, None),
    ("Located Volume Bn (Month)", "[All Located Volume Mn (Month)] / 1000", DEC2, F_GEO, None),
    ("State Share of Located %", "DIVIDE ( [Located Volume Mn (Month)], [All Located Volume Mn (Month)] )", PCT, F_GEO, None),
    ("Unclassified Share % (Month)", """
DIVIDE (
    CALCULATE ( [State Volume Mn (Month)], REMOVEFILTERS ( DimState ), DimState[Classified] = "No" ),
    CALCULATE ( [State Volume Mn (Month)], REMOVEFILTERS ( DimState ) )
)
""", PCT, F_GEO, "Share of transactions NPCI reports without a state."),
    ("State YoY % (Month)", """
VAR _cur = [Located Volume Mn (Month)]
VAR _ly = CALCULATE ( [State Volume Mn (Same Month LY)], KEEPFILTERS ( DimState[Classified] = "Yes" ) )
RETURN
    IF ( NOT ISBLANK ( _cur ) && _ly > 0, DIVIDE ( _cur - _ly, _ly ) )
""", GROWTH, F_GEO, None),
    ("State Avg Ticket ₹ (Month)",
     'CALCULATE ( DIVIDE ( [State Value Cr (Month)], [State Volume Mn (Month)] ) * 10, KEEPFILTERS ( DimState[Classified] = "Yes" ) )',
     RUPEE, F_GEO, None),
    ("Top State (Month)", """
VAR _t = TOPN ( 1, FILTER ( ALL ( DimState ), DimState[Classified] = "Yes" ), [State Volume Mn (Month)], DESC )
RETURN
    MAXX ( _t, DimState[State Name] )
""", None, F_GEO, None),
    ("Top State Share % (Month)", """
VAR _t = TOPN ( 1, FILTER ( ALL ( DimState ), DimState[Classified] = "Yes" ), [State Volume Mn (Month)], DESC )
RETURN
    DIVIDE ( SUMX ( _t, [State Volume Mn (Month)] ), [All Located Volume Mn (Month)] )
""", PCT, F_GEO, None),
    ("Top 5 States Share % (Month)", """
VAR _t = TOPN ( 5, FILTER ( ALL ( DimState ), DimState[Classified] = "Yes" ), [State Volume Mn (Month)], DESC )
RETURN
    DIVIDE ( SUMX ( _t, [State Volume Mn (Month)] ), [All Located Volume Mn (Month)] )
""", PCT, F_GEO, None),
    ("Top 15 State Volume Mn (Month)", """
VAR _v = [Located Volume Mn (Month)]
VAR _r =
    RANKX (
        FILTER ( ALL ( DimState[State Name], DimState[Classified] ), DimState[Classified] = "Yes" ),
        [Located Volume Mn (Month)], , DESC
    )
RETURN
    IF ( NOT ISBLANK ( _v ) && _r <= 15, _v )
""", INT, F_GEO, None),
    ("Top 10 State Avg Ticket ₹ (Month)", """
VAR _v = [Located Volume Mn (Month)]
VAR _r =
    RANKX (
        FILTER ( ALL ( DimState[State Name], DimState[Classified] ), DimState[Classified] = "Yes" ),
        [Located Volume Mn (Month)], , DESC
    )
RETURN
    IF ( NOT ISBLANK ( _v ) && _r <= 10, [State Avg Ticket ₹ (Month)] )
""", RUPEE, F_GEO, "Average payment for the 10 states with the most transactions."),
    ("Highest Avg Payment State (Month)", """
VAR _t =
    TOPN (
        1,
        FILTER ( ALL ( DimState ), DimState[Classified] = "Yes" && [State Volume Mn (Month)] >= 100 ),
        [State Avg Ticket ₹ (Month)], DESC
    )
RETURN
    MAXX ( _t, DimState[State Name] )
""", None, F_GEO, "State with the highest average payment among states with at least 100 mn transactions in the month."),
    ("Highest Avg Payment ₹ (Month)", """
VAR _t =
    TOPN (
        1,
        FILTER ( ALL ( DimState ), DimState[Classified] = "Yes" && [State Volume Mn (Month)] >= 100 ),
        [State Avg Ticket ₹ (Month)], DESC
    )
RETURN
    MAXX ( _t, [State Avg Ticket ₹ (Month)] )
""", RUPEE, F_GEO, None),

    # ---------------------------------------------------------------- text shown in the report
    ("Market Headline", """
VAR _old = [Avg Ticket ₹ (3 Years Earlier)]
RETURN
    "UPI processed " & FORMAT ( [Volume Bn (Month)], "0.00" ) & " bn payments (₹"
        & FORMAT ( [Value Lakh Cr (Month)], "0.00" ) & " lakh crore) in " & [Selected Month] & ", "
        & FORMAT ( [Volume YoY % (Month)], "+0.0%;-0.0%" ) & " on a year ago. Average payment: ₹"
        & FORMAT ( [Avg Ticket ₹ (Month)], "#,0" ) & IF ( ISBLANK ( _old ), ".", ", vs ₹" & FORMAT ( _old, "#,0" ) & " three years earlier." )
""", None, F_TXT, None),
    ("Competition Headline", """
IF (
    ISBLANK ( [Top 2 Apps Share % (Month)] ),
    "App-level data starts in April 2023. Pick a later month.",
    "PhonePe + Google Pay = " & FORMAT ( [Top 2 Apps Share % (Month)], "0.0%" )
        & " of UPI payments (HHI " & FORMAT ( [Market Concentration HHI (Month)], "#,0" )
        & IF ( [Market Concentration HHI (Month)] > 2500, ": highly concentrated", ": moderately concentrated" )
        & "). To meet the 30% cap, PhonePe must shift "
        & FORMAT ( [Volume Above Cap Mn (Month)] / 1000, "0.0" ) & " bn payments a month."
)
""", None, F_TXT, None),
    ("Merchant Headline", """
IF (
    ISBLANK ( [P2M Share of Volume % (Month)] ),
    "Merchant data starts in April 2020. Pick a later month.",
    "Merchant payments are " & FORMAT ( [P2M Share of Volume % (Month)], "0%" ) & " of UPI transactions but only "
        & FORMAT ( [P2M Share of Value % (Month)], "0%" ) & " of the money: a typical shop payment is ₹"
        & FORMAT ( [Avg P2M Ticket ₹ (Month)], "#,0" ) & " vs ₹" & FORMAT ( [Avg P2P Ticket ₹ (Month)], "#,0" )
        & " for person-to-person transfers."
)
""", None, F_TXT, None),
    ("MDR Headline", """
"A " & FORMAT ( [MDR Rate (Selected)], "0.00%" ) & " fee on the " & FORMAT ( [High-Value Share (Selected)], "0%" )
    & " of merchant value above ₹2,000 would earn about ₹" & FORMAT ( [Est. MDR Revenue Cr (Month)], "#,0" )
    & " crore a month (₹" & FORMAT ( [Est. MDR Revenue Cr (Annualised)], "#,0" ) & " crore a year). Person-to-person payments stay free."
""", None, F_TXT, None),
    ("Bank Headline", """
IF (
    ISBLANK ( [Bank Volume Mn (Month)] ),
    "Bank performance data starts in April 2025. Pick a later month.",
    "In " & [Selected Month] & ", " & FORMAT ( [Approval Rate % (Month)], "0.0%" )
        & " of payments from the top 20 banks succeeded. Business declines (PIN, limits, balance): "
        & FORMAT ( [Business Decline % (Month)], "0.0%" ) & ". Bank system failures: " & FORMAT ( [Technical Decline % (Month)], "0.00%" ) & "."
)
""", None, F_TXT, None),
    ("Geography Headline", """
IF (
    ISBLANK ( [All Located Volume Mn (Month)] ),
    "State data starts in April 2025. Pick a later month.",
    [Top State (Month)] & " has " & FORMAT ( [Top State Share % (Month)], "0.0%" )
        & " of located UPI payments and the top 5 states " & FORMAT ( [Top 5 States Share % (Month)], "0%" )
        & ". " & FORMAT ( [Unclassified Share % (Month)], "0%" ) & " of payments carry no state tag in NPCI data."
)
""", None, F_TXT, None),
    ("Insight Growth", """
VAR _old = [Avg Ticket ₹ (3 Years Earlier)]
VAR _n = [Months to 30 Bn]
RETURN
    IF (
        ISBLANK ( [Volume Bn (Month)] ),
        "No UPI data for this month.",
        "UPI handled " & FORMAT ( [Volume Bn (Month)], "0.00" ) & " bn payments worth ₹" & FORMAT ( [Value Lakh Cr (Month)], "0.00" )
            & " lakh crore in " & [Selected Month] & ", " & FORMAT ( [Volume YoY % (Month)], "+0.0%;-0.0%" )
            & " on a year earlier and about " & FORMAT ( [Daily Transactions Mn (Month)], "#,0" ) & " mn a day. "
            & "The average payment is ₹" & FORMAT ( [Avg Ticket ₹ (Month)], "#,0" )
            & IF ( ISBLANK ( _old ), "", " (₹" & FORMAT ( _old, "#,0" ) & " three years earlier)" )
            & " as small everyday payments move to UPI. "
            & IF (
                ISBLANK ( _n ), "",
                IF ( _n = 0, "UPI is already above 30 bn payments a month.",
                    "At this growth rate UPI reaches 30 bn payments a month around " & [30 Bn Month Projection] & "." )
            )
    )
""", None, F_TXT, None),
    ("Insight Competition", """
VAR _fast = [Fastest Growing App (Month)]
RETURN
    IF (
        ISBLANK ( [Top 2 Apps Share % (Month)] ),
        "App-level data starts in April 2023. Pick a later month.",
        "PhonePe (" & FORMAT ( [PhonePe Share % (Month)], "0.0%" ) & ") and Google Pay ("
            & FORMAT ( [Google Pay Share % (Month)], "0.0%" ) & ") process " & FORMAT ( [Top 2 Apps Share % (Month)], "0.0%" )
            & " of UPI payments"
            & IF (
                ISBLANK ( [Top 2 Apps Share % (Same Month LY)] ), "",
                ", " & IF ( [Top 2 Apps Share % (Month)] < [Top 2 Apps Share % (Same Month LY)], "down ", "up " )
                    & FORMAT ( ABS ( [Top 2 Apps Share % (Month)] - [Top 2 Apps Share % (Same Month LY)] ) * 100, "0.0" ) & " pts in a year"
            )
            & " (HHI " & FORMAT ( [Market Concentration HHI (Month)], "#,0" )
            & IF ( [Market Concentration HHI (Month)] > 2500, ", highly concentrated). ", ", moderately concentrated). " )
            & "To meet NPCI's 30% cap by 31 Dec 2026, PhonePe would need to move "
            & FORMAT ( [Volume Above Cap Mn (Month)] / 1000, "0.0" ) & " bn payments a month to rivals."
            & IF ( ISBLANK ( _fast ), "", " Fastest-growing challenger: " & _fast & "." )
    )
""", None, F_TXT, None),
    ("Insight Merchants", """
VAR _cat = [Top Category (Month)]
RETURN
    IF (
        ISBLANK ( [P2M Share of Volume % (Month)] ),
        "Merchant data starts in April 2020. Pick a later month.",
        "Merchant payments are " & FORMAT ( [P2M Share of Volume % (Month)], "0%" ) & " of UPI transactions but only "
            & FORMAT ( [P2M Share of Value % (Month)], "0%" ) & " of the value. A typical shop payment is ₹"
            & FORMAT ( [Avg P2M Ticket ₹ (Month)], "#,0" ) & ", against ₹" & FORMAT ( [Avg P2P Ticket ₹ (Month)], "#,0" )
            & " for person-to-person transfers."
            & IF ( ISBLANK ( _cat ), "", " Biggest category: " & _cat & " with " & FORMAT ( [Top Category Volume Bn (Month)], "0.0" ) & " bn payments." )
    )
""", None, F_TXT, None),
    ("Insight MDR", """
VAR _m = [Est. MDR Revenue Cr (Month)]
RETURN
    IF (
        ISBLANK ( _m ),
        "Merchant data starts in April 2020. Pick a later month.",
        "NPCI's new merchant fee (0.4% on payments above ₹2,000, from 15 Oct 2026) would earn about ₹" & FORMAT ( _m, "#,0" )
            & " crore a month at " & [Selected Month Short] & " volumes, or ₹" & FORMAT ( _m * 12, "#,0" ) & " crore a year. "
            & "On the split reported in the press, customers' banks would get about ₹" & FORMAT ( _m * 0.4, "#,0" )
            & " crore and UPI apps ₹" & FORMAT ( _m * 0.2, "#,0" ) & " crore a month. Person-to-person payments stay free."
    )
""", None, F_TXT, None),
    ("Insight Banks", """
IF (
    ISBLANK ( [Bank Volume Mn (Month)] ),
    "Bank performance data starts in April 2025. Pick a later month.",
    FORMAT ( [Approval Rate % (Month)], "0.0%" ) & " of payment attempts from the 20 largest banks succeeded in " & [Selected Month]
        & ". Most failures are business declines such as a wrong PIN, low balance or daily limits ("
        & FORMAT ( [Business Decline % (Month)], "0.0%" ) & "); bank system failures are rare ("
        & FORMAT ( [Technical Decline % (Month)], "0.00%" ) & "). Lowest approval rate: " & [Lowest Approval Bank Name (Month)]
        & " (" & FORMAT ( [Lowest Approval Rate % (Month)], "0.0%" ) & ")."
)
""", None, F_TXT, None),
    ("Insight States", """
IF (
    ISBLANK ( [All Located Volume Mn (Month)] ),
    "State data starts in April 2025. Pick a later month.",
    [Top State (Month)] & " leads with " & FORMAT ( [Top State Share % (Month)], "0.0%" )
        & " of UPI payments that have a location, and the top 5 states hold " & FORMAT ( [Top 5 States Share % (Month)], "0%" )
        & ". Highest average payment among large states: " & [Highest Avg Payment State (Month)]
        & " (₹" & FORMAT ( [Highest Avg Payment ₹ (Month)], "#,0" ) & "). "
        & FORMAT ( [Unclassified Share % (Month)], "0%" ) & " of payments carry no state tag and are left out of state shares."
)
""", None, F_TXT, None),

    # KPI subtitles
    ("Sub Volume", growth_sub("[Volume Bn (Month)]", "[Volume Bn (Same Month LY)]"), None, F_TXT, None),
    ("Sub Value", growth_sub("[Value Lakh Cr (Month)]", "[Value Lakh Cr (Same Month LY)]"), None, F_TXT, None),
    ("Sub Ticket", """
VAR _o = [Avg Ticket ₹ (3 Years Earlier)]
RETURN
    IF ( ISBLANK ( _o ), "Average rupees per payment", "₹" & FORMAT ( _o, "#,0" ) & " three years earlier" )
""", None, F_TXT, None),
    ("Sub Daily", '"Banks live on UPI: " & FORMAT ( [Banks Live (Month)], "#,0" )', None, F_TXT, None),
    ("Sub Projection", """
VAR _g = [Volume YoY % (Month)]
RETURN
    IF (
        [Volume Bn (Month)] >= 30, "Already above 30 bn a month",
        IF ( _g > 0, "If " & FORMAT ( _g, "0.0%" ) & " yearly growth continues", "Needs positive growth" )
    )
""", None, F_TXT, None),
    ("Sub PhonePe", """
VAR _s = [PhonePe Share % (Month)]
RETURN
    IF ( ISBLANK ( _s ), "", FORMAT ( ABS ( _s - 0.3 ) * 100, "0.0" ) & " pts " & IF ( _s > 0.3, "above", "below" ) & " the 30% cap" )
""", None, F_TXT, None),
    ("Sub Google Pay", """
VAR _s = [Google Pay Share % (Month)]
RETURN
    IF ( ISBLANK ( _s ), "", FORMAT ( ABS ( _s - 0.3 ) * 100, "0.0" ) & " pts " & IF ( _s > 0.3, "above", "below" ) & " the 30% cap" )
""", None, F_TXT, None),
    ("Sub Top 2", pts_sub("[Top 2 Apps Share % (Month)]", "[Top 2 Apps Share % (Same Month LY)]"), None, F_TXT, None),
    ("Sub HHI", 'IF ( [Market Concentration HHI (Month)] > 2500, "Highly concentrated (above 2,500)", "Moderately concentrated" )',
     None, F_TXT, None),
    ("Sub Days", '"Cap deadline: 31 Dec 2026"', None, F_TXT, None),
    ("Sub P2M Vol Share", pts_sub("[P2M Share of Volume % (Month)]", "[P2M Share of Volume % (Same Month LY)]"), None, F_TXT, None),
    ("Sub P2M Val Share", pts_sub("[P2M Share of Value % (Month)]", "[P2M Share of Value % (Same Month LY)]"), None, F_TXT, None),
    ("Sub P2M Volume", growth_sub("[P2M Volume Bn (Month)]", "[P2M Volume Bn (Same Month LY)]"), None, F_TXT, None),
    ("Sub P2M Ticket", """
VAR _o = [Avg P2M Ticket ₹ (Same Month LY)]
RETURN
    IF ( ISBLANK ( _o ), "", "₹" & FORMAT ( _o, "#,0" ) & " in " & [Same Month LY Label] )
""", None, F_TXT, None),
    ("Sub P2P Ticket", """
VAR _o = [Avg P2P Ticket ₹ (Same Month LY)]
RETURN
    IF ( ISBLANK ( _o ), "", "₹" & FORMAT ( _o, "#,0" ) & " in " & [Same Month LY Label] )
""", None, F_TXT, None),
    ("Sub MDR Value", '"Merchant payments in " & [Selected Month Short]', None, F_TXT, None),
    ("Sub MDR Eligible", 'FORMAT ( [High-Value Share (Selected)], "0%" ) & " of it is in payments above ₹2,000"', None, F_TXT, None),
    ("Sub MDR Month", """
"At a " & FORMAT ( [MDR Rate (Selected)], "0.00%" ) & " fee"
    & IF ( [Cap Adjustment (Selected)] > 0, ", less " & FORMAT ( [Cap Adjustment (Selected)], "0%" ) & " for caps and exemptions", "" )
""", None, F_TXT, None),
    ("Sub MDR Year", '"12 × the monthly estimate"', None, F_TXT, None),
    ("Sub Approval", pts_sub("[Approval Rate % (Month)]", "[Approval Rate % (Same Month LY)]"), None, F_TXT, None),
    ("Sub BD", pts_sub("[Business Decline % (Month)]", "[Business Decline % (Same Month LY)]"), None, F_TXT, None),
    ("Sub TD", pts_sub("[Technical Decline % (Month)]", "[Technical Decline % (Same Month LY)]", "0.00"), None, F_TXT, None),
    ("Sub Failed", '"Out of " & FORMAT ( [Bank Volume Mn (Month)] / 1000, "0.0" ) & " bn payment attempts"', None, F_TXT, None),
    ("Sub Lowest Approval", '"Approval rate: " & FORMAT ( [Lowest Approval Rate % (Month)], "0.0%" )', None, F_TXT, None),
    ("Sub Top State", 'FORMAT ( [Top State Share % (Month)], "0.0%" ) & " of payments with a state tag"', None, F_TXT, None),
    ("Sub Top 5", '"Of 36 states and union territories"', None, F_TXT, None),
    ("Sub Located", growth_sub("[All Located Volume Mn (Month)]", "[All Located Volume Mn (Same Month LY)]"), None, F_TXT, None),
    ("Sub Highest Avg", '"₹" & FORMAT ( [Highest Avg Payment ₹ (Month)], "#,0" ) & " a payment (100 mn+ states)"', None, F_TXT, None),
    ("Sub Unclassified", '"Left out of state shares"', None, F_TXT, None),

    # ---------------------------------------------------------------- colours
    ("Color Neutral", f'"{NEUTRAL_TEXT}"', None, F_CLR, None),
    ("Color Volume", sign_color("[Volume YoY % (Month)]"), None, F_CLR, None),
    ("Color Value", sign_color("[Value YoY % (Month)]"), None, F_CLR, None),
    ("Color PhonePe", f'IF ( [PhonePe Share % (Month)] > 0.3, "{BAD}", "{GOOD_TEXT}" )', None, F_CLR, None),
    ("Color Google Pay", f'IF ( [Google Pay Share % (Month)] > 0.3, "{BAD}", "{GOOD_TEXT}" )', None, F_CLR, None),
    ("Color HHI", f'IF ( [Market Concentration HHI (Month)] > 2500, "{BAD}", "{NEUTRAL_TEXT}" )', None, F_CLR, None),
    ("Color P2M Vol Share", sign_color("[P2M Share of Volume % (Month)] - [P2M Share of Volume % (Same Month LY)]"), None, F_CLR, None),
    ("Color P2M Val Share", sign_color("[P2M Share of Value % (Month)] - [P2M Share of Value % (Same Month LY)]"), None, F_CLR, None),
    ("Color P2M Volume", sign_color("[P2M Volume Bn (Month)] - [P2M Volume Bn (Same Month LY)]"), None, F_CLR, None),
    ("Color Approval", sign_color("[Approval Rate % (Month)] - [Approval Rate % (Same Month LY)]"), None, F_CLR, None),
    ("Color BD", sign_color("[Business Decline % (Month)] - [Business Decline % (Same Month LY)]", up_is_good=False), None, F_CLR, None),
    ("Color TD", sign_color("[Technical Decline % (Month)] - [Technical Decline % (Same Month LY)]", up_is_good=False), None, F_CLR, None),
    ("Color Located", sign_color("[All Located Volume Mn (Month)] - [All Located Volume Mn (Same Month LY)]"), None, F_CLR, None),
    ("Color Cap Bar", f'IF ( [App Share % (Month)] > 0.3, "{BAD}", "{BLUE}" )', None, F_CLR,
     "Red bars for apps above NPCI's 30% cap."),
    ("Color Growth Bar", f'IF ( [App Volume YoY % (Month)] < 0, "{BAD}", "{GOOD}" )', None, F_CLR, None),
    ("Color Category Growth", f'IF ( [Merchant Volume YoY % (Month)] < 0, "{BAD}", "{GOOD_TEXT}" )', None, F_CLR, None),
    ("Color State Growth", f'IF ( [State YoY % (Month)] < 0, "{BAD}", "{GOOD_TEXT}" )', None, F_CLR, None),
    ("Color Bank Type", f"""
SWITCH (
    SELECTEDVALUE ( DimBank[Bank Type] ),
    "Payments bank", "{BLUE}",
    "Private bank", "{ORANGE}",
    "Public sector bank", "{AQUA}",
    "{MUTED}"
)
""", None, F_CLR, "Same colour per bank type as the legend of the scatter and trend charts."),
]


def build_model():
    defn = SM / "definition"
    write(defn / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")

    tables = [
        "_Measures", "DimDate", "DimApp", "DimBank", "DimState", "DimMerchantCategory",
        "FactUPIMonthly", "FactP2PP2M", "FactAppMonthly", "FactMerchantCategory", "FactStateMonthly",
        "FactBankPerformance", "MDR Rate Options", "High Value Share Options", "Cap Adjustment Options", "MDR Split",
    ]
    m_queries = ["DimApp", "DimBank", "DimState", "DimMerchantCategory", "FactUPIMonthly", "FactP2PP2M",
                 "FactAppMonthly", "FactMerchantCategory", "FactStateMonthly", "FactBankPerformance"]
    model = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: en-US",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        "annotation PBI_QueryOrder = " + json.dumps(m_queries),
        "",
    ]
    model += [f"ref table {q(t)}" for t in tables]
    write(defn / "model.tmdl", "\n".join(model) + "\n")

    T = defn / "tables"
    txt, num, i64 = "type text", "type number", "Int64.Type"

    write(T / "_Measures.tmdl", table_tmdl(
        "_Measures", [col("Dummy", "int64", "[Dummy]", hidden=True, inferred=True)],
        "calculated", 'ROW ( "Dummy", 0 )', measures=MEASURES,
        description="All report measures, grouped in display folders by report page."))

    date_src = """
VAR _last = MAX ( FactUPIMonthly[Date] )
VAR _months = FILTER ( CALENDAR ( DATE ( 2016, 4, 1 ), _last ), DAY ( [Date] ) = 1 )
RETURN
    ADDCOLUMNS (
        _months,
        "Year", YEAR ( [Date] ),
        "Month Number", MONTH ( [Date] ),
        "Month Name", FORMAT ( [Date], "mmm" ),
        "Month", FORMAT ( [Date], "mmm yyyy" ),
        "Month Index", YEAR ( [Date] ) * 12 + MONTH ( [Date] ),
        "FY Start Year", IF ( MONTH ( [Date] ) >= 4, YEAR ( [Date] ), YEAR ( [Date] ) - 1 ),
        "Fiscal Year", "FY" & IF ( MONTH ( [Date] ) >= 4, YEAR ( [Date] ), YEAR ( [Date] ) - 1 ) & "-"
            & RIGHT ( IF ( MONTH ( [Date] ) >= 4, YEAR ( [Date] ), YEAR ( [Date] ) - 1 ) + 1, 2 )
    )
"""
    write(T / "DimDate.tmdl", table_tmdl("DimDate", [
        col("Date", "dateTime", "[Date]", fmt="mmm yyyy", key=True, inferred=True),
        col("Year", "int64", "[Year]", fmt="0", inferred=True),
        col("Month Number", "int64", "[Month Number]", fmt="0", inferred=True, hidden=True),
        col("Month Name", "string", "[Month Name]", inferred=True, sort_by="Month Number"),
        col("Month", "string", "[Month]", inferred=True, sort_by="Month Index",
            description="Reporting month, e.g. Aug 2026."),
        col("Month Index", "int64", "[Month Index]", fmt="0", inferred=True, hidden=True),
        col("FY Start Year", "int64", "[FY Start Year]", fmt="0", inferred=True, hidden=True),
        col("Fiscal Year", "string", "[Fiscal Year]", inferred=True, sort_by="FY Start Year",
            description="Indian fiscal year, April to March."),
    ], "calculated", date_src, data_category="Time",
        description="One row per month from April 2016 to the latest month in the data."))

    write(T / "DimApp.tmdl", table_tmdl("DimApp", [
        col("App", "string"), col("App Group", "string", sort_by="App Group Sort"),
        col("App Group Sort", "int64", hidden=True, fmt="0"), col("Segment", "string"), col("App Type", "string"),
    ], "m", m_query("dim_app.csv", 5, dim_steps(
        [("app", txt), ("app_group", txt), ("app_group_sort", i64), ("segment", txt), ("app_type", txt)],
        [("app", "App"), ("app_group", "App Group"), ("app_group_sort", "App Group Sort"),
         ("segment", "Segment"), ("app_type", "App Type")])),
        description="UPI apps with their market group and type."))

    write(T / "DimBank.tmdl", table_tmdl("DimBank", [
        col("Bank Key", "string", hidden=True), col("Bank", "string"), col("Bank Type", "string"),
    ], "m", m_query("dim_bank.csv", 3, dim_steps(
        [("bank_key", txt), ("bank", txt), ("bank_type", txt)],
        [("bank_key", "Bank Key"), ("bank", "Bank"), ("bank_type", "Bank Type")])),
        description="Clean bank names and type. Bank Key is the upper-case NPCI name, which varies in capitalisation month to month."))

    write(T / "DimState.tmdl", table_tmdl("DimState", [
        col("State", "string", hidden=True), col("State Name", "string", category="StateOrProvince"),
        col("Region", "string"), col("Classified", "string"),
    ], "m", m_query("dim_state.csv", 4, dim_steps(
        [("state", txt), ("state_name", txt), ("region", txt), ("classified", txt)],
        [("state", "State"), ("state_name", "State Name"), ("region", "Region"), ("classified", "Classified")])),
        description="States and union territories with region. Classified = No for NPCI's unclassified bucket."))

    write(T / "DimMerchantCategory.tmdl", table_tmdl("DimMerchantCategory", [
        col("MCC", "string"), col("Category", "string"), col("Sector", "string"),
    ], "m", m_query("dim_merchant_category.csv", 3, dim_steps(
        [("mcc", txt), ("category", txt), ("sector", txt)],
        [("mcc", "MCC"), ("category", "Category"), ("sector", "Sector")])),
        description="Merchant category codes (MCC) with short names and a sector grouping."))

    upi_steps = [
        'Typed = Table.TransformColumnTypes(Promoted, {{"month", type text}, {"banks_live", Int64.Type}, '
        '{"volume_mn", type number}, {"value_cr", type number}}, "en-US")',
        f"MonthNames = {MONTHS_LONG}",
        'AddDate = Table.AddColumn(Typed, "Date", each #date(Number.From(Text.AfterDelimiter([month], "-")), '
        'List.PositionOf(MonthNames, Text.BeforeDelimiter([month], "-")) + 1, 1), type date)',
        'Renamed = Table.RenameColumns(AddDate, {{"banks_live", "Banks Live"}, {"volume_mn", "Volume Mn"}, {"value_cr", "Value Cr"}})',
        'Sorted = Table.Sort(Renamed, {{"Date", Order.Ascending}})',
        'Result = Table.SelectColumns(Sorted, {"Date", "Banks Live", "Volume Mn", "Value Cr"})',
    ]
    write(T / "FactUPIMonthly.tmdl", table_tmdl("FactUPIMonthly", [
        col("Date", "dateTime", fmt="mmm yyyy"), col("Banks Live", "int64", fmt="#,0", summarize="sum"),
        col("Volume Mn", "double", fmt="#,0.00", summarize="sum"), col("Value Cr", "double", fmt="#,0.00", summarize="sum"),
    ], "m", m_query("upi_monthly_totals.csv", 4, upi_steps),
        description="NPCI monthly UPI totals since April 2016 (volume in millions, value in rupees crore)."))

    p2p_steps = [
        'Typed = Table.TransformColumnTypes(Promoted, {{"year", Int64.Type}, {"month", type text}, {"p2p_volume_mn", type number}, '
        '{"p2p_value_cr", type number}, {"p2m_volume_mn", type number}, {"p2m_value_cr", type number}}, "en-US")',
        f"MonthNames = {MONTHS_SHORT}",
        'AddDate = Table.AddColumn(Typed, "Date", each #date([year], List.PositionOf(MonthNames, [month]) + 1, 1), type date)',
        'P2P = Table.AddColumn(Table.RenameColumns(Table.SelectColumns(AddDate, {"Date", "p2p_volume_mn", "p2p_value_cr"}), '
        '{{"p2p_volume_mn", "Volume Mn"}, {"p2p_value_cr", "Value Cr"}}), "Payment Type", each "P2P", type text)',
        'P2M = Table.AddColumn(Table.RenameColumns(Table.SelectColumns(AddDate, {"Date", "p2m_volume_mn", "p2m_value_cr"}), '
        '{{"p2m_volume_mn", "Volume Mn"}, {"p2m_value_cr", "Value Cr"}}), "Payment Type", each "P2M", type text)',
        "Combined = Table.Combine({P2P, P2M})",
        'Result = Table.TransformColumnTypes(Combined, {{"Volume Mn", type number}, {"Value Cr", type number}, {"Payment Type", type text}})',
    ]
    write(T / "FactP2PP2M.tmdl", table_tmdl("FactP2PP2M", [
        col("Date", "dateTime", fmt="mmm yyyy"), col("Volume Mn", "double", fmt="#,0.00", summarize="sum"),
        col("Value Cr", "double", fmt="#,0.00", summarize="sum"), col("Payment Type", "string"),
    ], "m", m_query("upi_p2p_p2m.csv", 6, p2p_steps),
        description="Person-to-person (P2P) vs person-to-merchant (P2M) UPI payments, unpivoted to one row per type."))

    write(T / "FactAppMonthly.tmdl", table_tmdl("FactAppMonthly", [
        col("Date", "dateTime", fmt="mmm yyyy"), col("App", "string"),
        col("Volume Mn", "double", fmt="#,0.00", summarize="sum"), col("Value Cr", "double", fmt="#,0", summarize="sum"),
    ], "m", m_query("upi_apps.csv", 5, monthly_steps(
        [("app", txt), ("volume_mn", num), ("value_cr", num)], [],
        [("app", "App"), ("volume_mn", "Volume Mn"), ("value_cr", "Value Cr")], ["Date", "App", "Volume Mn", "Value Cr"])),
        description="Monthly UPI transactions by app (NPCI ecosystem statistics)."))

    write(T / "FactMerchantCategory.tmdl", table_tmdl("FactMerchantCategory", [
        col("Date", "dateTime", fmt="mmm yyyy"), col("MCC", "string"),
        col("Volume Mn", "double", fmt="#,0.00", summarize="sum"), col("Value Cr", "double", fmt="#,0", summarize="sum"),
    ], "m", m_query("upi_merchant_category.csv", 5, monthly_steps(
        [("mcc", txt), ("volume_mn", num), ("value_cr", num)], [],
        [("mcc", "MCC"), ("volume_mn", "Volume Mn"), ("value_cr", "Value Cr")], ["Date", "MCC", "Volume Mn", "Value Cr"])),
        description="Monthly merchant payments by merchant category code (top ~30 categories + all others)."))

    write(T / "FactStateMonthly.tmdl", table_tmdl("FactStateMonthly", [
        col("Date", "dateTime", fmt="mmm yyyy"), col("State", "string"),
        col("Volume Mn", "double", fmt="#,0.00", summarize="sum"), col("Value Cr", "double", fmt="#,0", summarize="sum"),
    ], "m", m_query("upi_state.csv", 5, monthly_steps(
        [("state", txt), ("volume_mn", num), ("value_cr", num)], [],
        [("state", "State"), ("volume_mn", "Volume Mn"), ("value_cr", "Value Cr")], ["Date", "State", "Volume Mn", "Value Cr"])),
        description="Monthly UPI transactions by state (district rows summed to state level)."))

    write(T / "FactBankPerformance.tmdl", table_tmdl("FactBankPerformance", [
        col("Date", "dateTime", fmt="mmm yyyy"), col("Bank Key", "string", hidden=True),
        col("Volume Mn", "double", fmt="#,0.00", summarize="sum"),
        col("Approved %", "double", fmt="0.00%"),
        col("Business Decline %", "double", fmt="0.00%"),
        col("Technical Decline %", "double", fmt="0.00%"),
    ], "m", m_query("upi_bank_performance.csv", 7, monthly_steps(
        [("bank", txt), ("volume_mn", num), ("approved_pct", num), ("business_decline_pct", num), ("technical_decline_pct", num)],
        [("BankKey", 'Table.AddColumn({prev}, "Bank Key", each Text.Upper(Text.Trim([bank])), type text)'),
         ("AsFractions", 'Table.TransformColumns({prev}, {{"approved_pct", each _ / 100, type number}, '
                         '{"business_decline_pct", each _ / 100, type number}, {"technical_decline_pct", each _ / 100, type number}})')],
        [("volume_mn", "Volume Mn"), ("approved_pct", "Approved %"), ("business_decline_pct", "Business Decline %"),
         ("technical_decline_pct", "Technical Decline %")],
        ["Date", "Bank Key", "Volume Mn", "Approved %", "Business Decline %", "Technical Decline %"])),
        description="Monthly performance of the 20 largest sending (remitter) banks: approvals and declines."))

    def option_table(name, label_col, value_col, value_fmt, rows, description):
        body = ",\n".join(f'        {{ "{label}", {value}, {i + 1} }}' for i, (label, value) in enumerate(rows))
        src = (f'DATATABLE (\n    "{label_col}", STRING, "{value_col}", DOUBLE, "Sort", INTEGER,\n    {{\n'
               f"{body}\n    }}\n)")
        write(T / f"{name}.tmdl", table_tmdl(name, [
            col(label_col, "string", f"[{label_col}]", inferred=True, sort_by="Sort"),
            col(value_col, "double", f"[{value_col}]", fmt=value_fmt, inferred=True),
            col("Sort", "int64", "[Sort]", hidden=True, inferred=True),
        ], "calculated", src, description=description))

    # The first option of each list is the default: single-select slicers open on the first item.
    option_table("MDR Rate Options", "MDR Rate Option", "MDR Rate", "0.00%",
                 [("0.40%", 0.004), ("0.25%", 0.0025), ("0.30%", 0.003), ("0.50%", 0.005)],
                 "What-if options for the merchant discount rate. First option = NPCI rate of 0.40% (default).")
    option_table("High Value Share Options", "Share Option", "Share", "0%",
                 [("67%", 0.67), ("55%", 0.55), ("60%", 0.60), ("70%", 0.70), ("75%", 0.75)],
                 "What-if options for the share of merchant value in payments above Rs 2,000. First option = reported 67%.")
    option_table("Cap Adjustment Options", "Adjustment Option", "Adjustment", "0%",
                 [("None", 0), ("-10%", 0.10), ("-20%", 0.20), ("-30%", 0.30)],
                 "What-if reduction for the Rs 300 cap, Rs 5 flat-fee sectors and the small-merchant exemption.")
    option_table("MDR Split", "Party", "Share", "0%",
                 [("Customer's bank", 0.40), ("Merchant's bank", 0.30), ("UPI app", 0.20), ("App's partner bank", 0.10)],
                 "How the MDR is shared between participants, as reported in the press (IBTimes, 25 Sep 2026).")

    rels = [
        ("FactUPIMonthly", "Date", "DimDate", "Date"),
        ("FactP2PP2M", "Date", "DimDate", "Date"),
        ("FactAppMonthly", "Date", "DimDate", "Date"),
        ("FactMerchantCategory", "Date", "DimDate", "Date"),
        ("FactStateMonthly", "Date", "DimDate", "Date"),
        ("FactBankPerformance", "Date", "DimDate", "Date"),
        ("FactAppMonthly", "App", "DimApp", "App"),
        ("FactMerchantCategory", "MCC", "DimMerchantCategory", "MCC"),
        ("FactStateMonthly", "State", "DimState", "State"),
        ("FactBankPerformance", "Bank Key", "DimBank", "Bank Key"),
    ]
    lines = []
    for ft, fc, tt, tc in rels:
        lines += [f"relationship {guid('rel:' + ft + fc + tt)}",
                  f"\tfromColumn: {q(ft)}.{q(fc)}",
                  f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    write(defn / "relationships.tmdl", "\n".join(lines))

    write_json(SM / "definition.pbism", {
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0",
        "settings": {},
    })
    write_json(SM / ".platform", {
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": guid("logical:model")},
    })


# ==============================================================================================
# Report (PBIR)
# ==============================================================================================

def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + text.replace("'", "''") + "'")


def b(flag):
    return lit("true" if flag else "false")


def d(num):
    return lit(f"{num}D")


def i(num):
    return lit(f"{num}L")


def color(hexv):
    return {"solid": {"color": s(hexv)}}


def fcol(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def fmeas(prop, entity="_Measures"):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mexpr(measure):
    return {"expr": fmeas(measure)}


def mcolor(measure):
    return {"solid": {"color": mexpr(measure)}}


def qref(field):
    kind = "Measure" if "Measure" in field else "Column"
    return f'{field[kind]["Expression"]["SourceRef"]["Entity"]}.{field[kind]["Property"]}'


def proj(field, display=None):
    kind = "Measure" if "Measure" in field else "Column"
    p = {"field": field, "queryRef": qref(field), "nativeQueryRef": field[kind]["Property"]}
    if display:
        p["displayName"] = display
    return p


WILDCARD = {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}


class Page:
    def __init__(self, name, display):
        self.name, self.display = name, display
        self.visuals = []
        self.no_filter_from_slicer = []

    def add(self, vname, x, y, w, h, visual, title=None, subtitle=None, subtitle_measure=None,
            subtitle_color_measure=None, alt=None, container=None, z=None):
        vco = {"title": [{"properties": {"show": b(title is not None), **({"text": s(title)} if title else {})}}]}
        if subtitle or subtitle_measure:
            props = {"show": b(True), "text": mexpr(subtitle_measure) if subtitle_measure else s(subtitle),
                     "fontSize": d(9), "fontColor": mcolor(subtitle_color_measure) if subtitle_color_measure else color(INK2)}
            vco["subTitle"] = [{"properties": props}]
        if alt or title:
            vco["general"] = [{"properties": {"altText": s(alt or title)}}]
        if container:
            vco.update(container)
        visual["visualContainerObjects"] = vco
        idx = len(self.visuals)
        self.visuals.append({
            "$schema": f"{SCHEMA}/item/report/definition/visualContainer/{V_VISUAL}/schema.json",
            "name": vname,
            "position": {"x": x, "y": y, "z": z if z is not None else idx * 1000,
                         "height": h, "width": w, "tabOrder": idx * 1000},
            "visual": visual,
        })
        return vname


NO_CHROME = {"background": [{"properties": {"show": b(False)}}], "border": [{"properties": {"show": b(False)}}]}


def textbox(paragraphs):
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]}}


def para(*runs):
    return {"textRuns": [{"value": t, "textStyle": st} for t, st in runs]}


def run(text, size=10, bold=False, col=INK2):
    st = {"fontSize": f"{size}pt", "color": col, "fontFamily": "Segoe UI"}
    if bold:
        st["fontWeight"] = "bold"
    return (text, st)


def card(measure, size=24, col_hex=INK, wrap=False):
    objs = {
        "labels": [{"properties": {"color": color(col_hex), "fontSize": d(size), "labelDisplayUnits": d(1),
                                   "fontFamily": s("Segoe UI Semibold")}}],
        "categoryLabels": [{"properties": {"show": b(False)}}],
    }
    if wrap:
        objs["wordWrap"] = [{"properties": {"show": b(True)}}]
    return {"visualType": "card", "query": {"queryState": {"Values": {"projections": [proj(fmeas(measure))]}}},
            "objects": objs}


def chart(vtype, sort=None, labels=False, legend=None, color_measure=None, ref_line=None, extra=None, **roles):
    qs = {}
    for role, fields in roles.items():
        qs[role] = {"projections": [proj(f[0], f[1]) if isinstance(f, tuple) else proj(f) for f in fields]}
    v = {"visualType": vtype, "query": {"queryState": qs}}
    if sort:
        field, direction = sort
        v["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}], "isDefaultSort": False}
    objs = {}
    if labels:
        objs["labels"] = [{"properties": {"show": b(True), "fontSize": d(8), "color": color(INK2), "labelDisplayUnits": d(1)}}]
    if vtype in ("clusteredBarChart", "clusteredColumnChart", "scatterChart", "areaChart", "lineChart"):
        # Show plain numbers (e.g. 3,996) instead of auto units (4.0K) on value axes.
        objs["valueAxis"] = [{"properties": {"labelDisplayUnits": d(1)}}]
    if vtype == "scatterChart":
        objs["categoryAxis"] = [{"properties": {"labelDisplayUnits": d(1)}}]
    if vtype == "clusteredBarChart":
        # Leave room for long category names and fit up to ~20 bars without scrolling.
        objs["categoryAxis"] = [{"properties": {"maxMarginFactor": i(45), "preferredCategoryWidth": d(10)}}]
    if legend is not None:
        objs["legend"] = ([{"properties": {"show": b(False)}}] if legend is False else
                          [{"properties": {"show": b(True), "position": s(legend), "fontSize": d(8)}}])
    if color_measure:
        objs["dataPoint"] = [{"properties": {"fill": mcolor(color_measure)}, "selector": WILDCARD}]
    if ref_line:
        value, label, hexv = ref_line
        objs["y1AxisReferenceLine"] = [{
            "properties": {"show": b(True), "value": d(value), "lineColor": color(hexv), "style": s("dashed"),
                           "width": d(2), "displayName": s(label), "dataLabelShow": b(True), "dataLabelText": s("Name"),
                           "dataLabelColor": color(hexv), "dataLabelHorizontalPosition": s("right"),
                           "dataLabelVerticalPosition": s("above"), "position": s("front")},
            "selector": {"id": "0"}}]
    if extra:
        objs.update(extra)
    if objs:
        v["objects"] = objs
    return v


def table(values, widths, sort=None, font_color_rules=(), header_bg=NAVY, font_size=9):
    """Table with fixed column widths (so nothing is cut off), no total row and optional colour rules."""
    v = chart("tableEx", sort=sort, Values=values)
    objs = {
        "columnHeaders": [{"properties": {"fontColor": color(WHITE), "backColor": color(header_bg), "fontSize": d(font_size),
                                          "bold": b(True), "wordWrap": b(True), "columnAdjustment": s("fixedWidth")}}],
        "values": [{"properties": {"fontSize": d(font_size), "wordWrap": b(True), "fontColorPrimary": color(INK),
                                   "fontColorSecondary": color(INK), "backColorPrimary": color(WHITE),
                                   "backColorSecondary": color("#F7F8FC")}}],
        "grid": [{"properties": {"gridVertical": b(False), "gridHorizontal": b(True), "gridHorizontalColor": color(TILE_BORDER),
                                 "rowPadding": d(3)}}],
        "total": [{"properties": {"totals": b(False)}}],
        "columnWidth": [{"properties": {"value": d(w)}, "selector": {"metadata": qref(f[0] if isinstance(f, tuple) else f)}}
                        for f, w in zip(values, widths)],
    }
    for measure_field, color_measure in font_color_rules:
        objs["values"].append({"properties": {"fontColor": mcolor(color_measure)},
                               "selector": {**WILDCARD, "metadata": qref(measure_field)}})
    v["objects"] = objs
    return v


def insight_tile(measure, header):
    v = chart("tableEx", Values=[(fmeas(measure), header)])
    v["objects"] = {
        "columnHeaders": [{"properties": {"fontColor": color(WHITE), "backColor": color(NAVY), "fontSize": d(11),
                                          "bold": b(True), "columnAdjustment": s("growToFit"), "wordWrap": b(True)}}],
        "values": [{"properties": {"fontSize": d(12), "wordWrap": b(True), "fontColorPrimary": color(INK),
                                   "backColorPrimary": color(WHITE), "backColorSecondary": color(WHITE)}}],
        "grid": [{"properties": {"gridVertical": b(False), "gridHorizontal": b(False), "rowPadding": d(8)}}],
    }
    return v


def slicer(field, mode="Dropdown", single=True, sort_desc=False, sync=None, header_text=None, header=True, tiles=False):
    v = {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [dict(proj(field), active=True)]}}},
        "objects": {
            "data": [{"properties": {"mode": s("Basic" if tiles else mode)}}],
            "selection": [{"properties": {"strictSingleSelect": b(single), "singleSelect": b(True)}}],
            "header": [{"properties": {"show": b(header), "fontColor": color(INK), "textSize": d(9),
                                       **({"text": s(header_text)} if header_text else {})}}],
            "items": [{"properties": {"fontColor": color(INK), "textSize": d(10)}}],
        },
    }
    if tiles:
        # Horizontal orientation turns a list slicer into clickable tiles.
        v["objects"]["general"] = [{"properties": {"orientation": d(1), "responsive": b(True)}}]
    if sort_desc:
        v["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": "Descending"}], "isDefaultSort": False}
    if sync:
        v["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
    return v


def navigator():
    sel = lambda state: {"id": state}
    return {
        "visualType": "pageNavigator",
        "objects": {
            "fill": [
                {"properties": {"show": b(True), "fillColor": color(WHITE), "transparency": d(0)}, "selector": sel("default")},
                {"properties": {"fillColor": color("#E6EAF6")}, "selector": sel("hover")},
                {"properties": {"fillColor": color(NAVY)}, "selector": sel("selected")},
            ],
            "text": [
                {"properties": {"fontColor": color(INK), "fontSize": d(10), "fontFamily": s("Segoe UI Semibold")},
                 "selector": sel("default")},
                {"properties": {"fontColor": color(WHITE)}, "selector": sel("selected")},
            ],
            "outline": [
                {"properties": {"show": b(True), "lineColor": color("#D5DAE8"), "weight": d(1)}, "selector": sel("default")},
                {"properties": {"lineColor": color(NAVY)}, "selector": sel("selected")},
            ],
            "shape": [{"properties": {"tileShape": s("rectangle"), "rectangleRoundedCurve": i(6)}}],
        },
    }


BAND_H, NAV_Y, NAV_H, STRIP_Y, STRIP_H = 64, 70, 32, 108, 38
KPI_Y, KPI_H, CHART_Y, BOTTOM = 154, 96, 258, 712
NO_PAD = {"padding": [{"properties": {"top": d(0), "bottom": d(0), "left": d(0), "right": d(0)}}]}


def page_header(p, title, month_slicer=True):
    p.add("band", 0, 0, 1280, BAND_H, textbox([para(run(title, 18, True, WHITE))]), z=0,
          container={"background": [{"properties": {"show": b(True), "color": color(NAVY), "transparency": d(0)}}],
                     "border": [{"properties": {"show": b(False)}}],
                     "padding": [{"properties": {"top": d(2), "left": d(12)}}]})
    p.add("bandSub", 22, 36, 1000, 24, card("Page Subtitle", size=9, col_hex="#C9D1EA"),
          container={**NO_CHROME, **NO_PAD}, z=100)
    if month_slicer:
        p.add("month", 1070, 6, 194, 52,
              slicer(fcol("DimDate", "Month"), sort_desc=True, sync="Month", header_text="Month"),
              container={"background": [{"properties": {"show": b(True), "color": color(WHITE), "transparency": d(0)}}],
                         "border": [{"properties": {"show": b(False)}}],
                         "padding": [{"properties": {"top": d(2), "bottom": d(2), "left": d(8), "right": d(8)}}]}, z=200)
    p.add("nav", 16, NAV_Y, 1248, NAV_H, navigator(), container=NO_CHROME, z=300)


def headline_strip(p, measure):
    p.add("strip", 16, STRIP_Y, 1248, STRIP_H, card(measure, size=11, col_hex=INK, wrap=True),
          container={"background": [{"properties": {"show": b(True), "color": color(STRIP_BG), "transparency": d(0)}}],
                     "border": [{"properties": {"show": b(False)}}]})


def kpi_row(p, items, y=KPI_Y, h=KPI_H):
    n = len(items)
    gap = 12
    w = (1248 - gap * (n - 1)) / n
    for k, (measure, title, sub, sub_color, size) in enumerate(items):
        p.add(f"kpi{k + 1}", round(16 + k * (w + gap)), y, round(w), h, card(measure, size=size), title=title,
              subtitle_measure=sub, subtitle_color_measure=sub_color, alt=title)


D = lambda c: fcol("DimDate", c)
M = fmeas


def build_pages():
    pages = []

    # 1 Executive summary ----------------------------------------------------------------------
    p = Page("p1_summary", "Executive Summary")
    page_header(p, "UPI Market Intelligence  ·  Executive Summary")
    kpi_row(p, [
        ("Volume Bn (Month)", "Transactions (bn)", "Sub Volume", "Color Volume", 24),
        ("Value Lakh Cr (Month)", "Value (₹ lakh crore)", "Sub Value", "Color Value", 24),
        ("Top 2 Apps Share % (Month)", "PhonePe + Google Pay share", "Sub Top 2", "Color Neutral", 24),
        ("Est. MDR Revenue Cr (Annualised)", "New MDR fee (₹ crore a year)", "Sub MDR Year", "Color Neutral", 24),
        ("Approval Rate % (Month)", "Payment success (top 20 banks)", "Sub Approval", "Color Approval", 24),
    ], y=STRIP_Y, h=KPI_H)
    tiles = [("Insight Growth", "Growth"), ("Insight Competition", "Competition"), ("Insight Merchants", "Merchant payments"),
             ("Insight MDR", "The new merchant fee (MDR)"), ("Insight Banks", "Bank reliability"), ("Insight States", "States")]
    tw, ty0 = 408, STRIP_Y + KPI_H + 10
    th = (BOTTOM - ty0 - 10) // 2
    for k, (measure, header) in enumerate(tiles):
        r, c = divmod(k, 3)
        p.add(f"tile{k + 1}", 16 + c * (tw + 12), ty0 + r * (th + 10), tw, th, insight_tile(measure, header),
              alt=f"{header}: key finding for the selected month")
    pages.append(p)

    # 2 Market overview ------------------------------------------------------------------------
    p = Page("p2_market", "Market Overview")
    page_header(p, "Market Overview  ·  How big is UPI and how fast is it growing?")
    headline_strip(p, "Market Headline")
    kpi_row(p, [
        ("Volume Bn (Month)", "Transactions (bn)", "Sub Volume", "Color Volume", 24),
        ("Value Lakh Cr (Month)", "Value (₹ lakh crore)", "Sub Value", "Color Value", 24),
        ("Avg Ticket ₹ (Month)", "Average payment", "Sub Ticket", "Color Neutral", 24),
        ("Daily Transactions Mn (Month)", "Transactions per day (mn)", "Sub Daily", "Color Neutral", 24),
        ("30 Bn Month Projection", "30 bn payments a month by", "Sub Projection", "Color Neutral", 20),
    ])
    p.add("trend", 16, CHART_Y, 616, BOTTOM - CHART_Y, chart(
        "areaChart", ref_line=(30, "30 bn a month", ORANGE),
        Category=[D("Date")], Y=[(M("UPI Volume (Bn)"), "Transactions (bn)")]),
        title="Monthly UPI transactions (bn), April 2016 onwards",
        subtitle="Dashed line: 30 bn a month. Trend charts ignore the Month slicer.")
    half = (BOTTOM - CHART_Y - 12) // 2
    p.add("fy", 648, CHART_Y, 616, half, chart(
        "clusteredColumnChart", sort=(D("Fiscal Year"), "Ascending"), labels=True,
        Category=[D("Fiscal Year")], Y=[(M("UPI Volume since FY19 (Bn)"), "Transactions (bn)")]),
        title="Transactions by fiscal year (bn)", subtitle="FY2026-27 covers April to the latest month only")
    p.add("ticket", 648, CHART_Y + half + 12, 616, half, chart(
        "lineChart", Category=[D("Date")], Y=[(M("Avg Ticket Size since FY20 (₹)"), "Average payment (₹)")]),
        title="Average payment size (₹)", subtitle="Falling as small everyday payments move to UPI")
    p.no_filter_from_slicer = ["trend", "fy", "ticket"]
    pages.append(p)

    # 3 App competition ------------------------------------------------------------------------
    p = Page("p3_apps", "App Competition")
    page_header(p, "App Competition  ·  Who controls UPI?")
    headline_strip(p, "Competition Headline")
    kpi_row(p, [
        ("PhonePe Share % (Month)", "PhonePe share", "Sub PhonePe", "Color PhonePe", 24),
        ("Google Pay Share % (Month)", "Google Pay share", "Sub Google Pay", "Color Google Pay", 24),
        ("Top 2 Apps Share % (Month)", "Top 2 combined", "Sub Top 2", "Color Neutral", 24),
        ("Market Concentration HHI (Month)", "Concentration (HHI)", "Sub HHI", "Color HHI", 24),
        ("Days to Cap Deadline", "Days to the 30% cap deadline", "Sub Days", "Color Neutral", 24),
    ])
    p.add("shareTrend", 16, CHART_Y, 616, BOTTOM - CHART_Y, chart(
        "hundredPercentStackedColumnChart", legend="Top",
        Category=[D("Date")], Series=[fcol("DimApp", "App Group")], Y=[(M("App Volume (Mn)"), "Transactions (mn)")]),
        title="Market share by app, April 2023 onwards", subtitle="Share of UPI transactions each month")
    p.add("shareNow", 648, CHART_Y, 300, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(M("App Share % (Month)"), "Descending"), labels=True, color_measure="Color Cap Bar",
        ref_line=(0.3, "30% cap", BAD),
        Category=[fcol("DimApp", "App")], Y=[(M("App Share % (Month)"), "Market share")]),
        title="Market share in the selected month", subtitle="Red = above NPCI's 30% cap")
    p.add("growth", 960, CHART_Y, 304, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(M("App Volume YoY % (Month)"), "Descending"), labels=True, color_measure="Color Growth Bar",
        Category=[fcol("DimApp", "App")], Y=[(M("App Volume YoY % (Month)"), "Growth vs last year")]),
        title="Growth vs the same month last year", subtitle="Challengers are growing fastest")
    p.no_filter_from_slicer = ["shareTrend"]
    pages.append(p)

    # 4 Merchant payments ----------------------------------------------------------------------
    p = Page("p4_merchants", "Merchant Payments")
    page_header(p, "Merchant Payments  ·  Where do people spend?")
    headline_strip(p, "Merchant Headline")
    kpi_row(p, [
        ("P2M Share of Volume % (Month)", "Merchant share of transactions", "Sub P2M Vol Share", "Color P2M Vol Share", 24),
        ("P2M Share of Value % (Month)", "Merchant share of value", "Sub P2M Val Share", "Color P2M Val Share", 24),
        ("P2M Volume Bn (Month)", "Merchant payments (bn)", "Sub P2M Volume", "Color P2M Volume", 24),
        ("Avg P2M Ticket ₹ (Month)", "Average shop payment", "Sub P2M Ticket", "Color Neutral", 24),
        ("Avg P2P Ticket ₹ (Month)", "Average person-to-person transfer", "Sub P2P Ticket", "Color Neutral", 24),
    ])
    p.add("p2m", 16, CHART_Y, 400, BOTTOM - CHART_Y, chart(
        "lineChart", Category=[D("Date")], Y=[(M("P2M Share of Volume %"), "Merchant share of transactions")]),
        title="Merchant payments' share of UPI transactions", subtitle="April 2020 onwards")
    p.add("cats", 428, CHART_Y, 420, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(M("Top 15 Category Volume Mn (Month)"), "Descending"), labels=True,
        Category=[fcol("DimMerchantCategory", "Category")], Y=[(M("Top 15 Category Volume Mn (Month)"), "Transactions (mn)")]),
        title="Top 15 merchant categories (mn transactions)", subtitle="Click a bar to filter the table")
    half = (BOTTOM - CHART_Y - 12) // 2
    p.add("sectors", 860, CHART_Y, 404, half, chart(
        "treemap", Group=[fcol("DimMerchantCategory", "Sector")],
        Values=[(M("Named Category Value Cr (Month)"), "Value (₹ cr)")]),
        title="Where merchant money goes (value by sector)", subtitle="Named categories only")
    p.add("catTbl", 860, CHART_Y + half + 12, 404, half, table(
        [(fcol("DimMerchantCategory", "Category"), "Category"), (M("Named Category Value Cr (Month)"), "Value (₹ cr)"),
         (M("Named Category Avg Ticket ₹ (Month)"), "Avg payment"), (M("Named Category YoY % (Month)"), "Growth")],
        [150, 78, 72, 62],
        sort=(M("Named Category Value Cr (Month)"), "Descending"),
        font_color_rules=[(M("Named Category YoY % (Month)"), "Color Category Growth")]),
        title="Categories ranked by value", subtitle="High-value categories pay most of the new fee")
    p.no_filter_from_slicer = ["p2m"]
    pages.append(p)

    # 5 MDR simulator ----------------------------------------------------------------------------
    p = Page("p5_mdr", "MDR Simulator")
    page_header(p, "MDR Simulator  ·  What is the new merchant fee worth?")
    headline_strip(p, "MDR Headline")
    white_box = {"background": [{"properties": {"show": b(True), "color": color(WHITE), "transparency": d(0)}}]}
    sy, sh = KPI_Y, 96
    p.add("sRate", 16, sy, 300, sh, slicer(fcol("MDR Rate Options", "MDR Rate Option"), tiles=True, header=False),
          title="1. Fee rate  (NPCI: 0.40%)")
    p.add("sShare", 16, sy + sh + 8, 300, sh,
          slicer(fcol("High Value Share Options", "Share Option"), tiles=True, header=False),
          title="2. Share above ₹2,000  (reported: 67%)")
    p.add("sAdj", 16, sy + 2 * sh + 16, 300, sh,
          slicer(fcol("Cap Adjustment Options", "Adjustment Option"), tiles=True, header=False),
          title="3. Cut for caps and exemptions")
    note_y = sy + 3 * sh + 24
    p.add("note", 16, note_y, 300, BOTTOM - note_y, textbox([
        para(run("Rules (NPCI FAQ, 15 Sep 2026)", 9, True, INK)),
        para(run("From 15 Oct 2026 merchants pay 0.4% on UPI payments above ₹2,000, capped at ₹300. Fuel, railways, "
                 "telecom and insurance pay a flat ₹5. Person-to-person payments and small merchants (up to ₹1 lakh a "
                 "month via QR) stay free.", 8)),
        para(run("The 67% share and the 40/30/20/10 split are press figures, not NPCI data.", 8)),
    ]), container=white_box)
    xs, w = [328, 564, 800, 1036], 228
    for k, (m, t, sub) in enumerate([
            ("P2M Value Lakh Cr (Month)", "Merchant payment value (₹ lakh cr)", "Sub MDR Value"),
            ("MDR-Eligible Value Lakh Cr (Month)", "Value charged the fee (₹ lakh cr)", "Sub MDR Eligible"),
            ("Est. MDR Revenue Cr (Month)", "Est. fee revenue a month (₹ cr)", "Sub MDR Month"),
            ("Est. MDR Revenue Cr (Annualised)", "Est. fee revenue a year (₹ cr)", "Sub MDR Year")]):
        p.add(f"kpi{k + 1}", xs[k], KPI_Y, w, KPI_H, card(m, size=24), title=t, subtitle_measure=sub,
              subtitle_color_measure="Color Neutral")
    p.add("split", 328, CHART_Y, 460, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(fcol("MDR Split", "Party"), "Ascending"), labels=True,
        Category=[fcol("MDR Split", "Party")], Y=[(M("MDR Revenue by Party Cr"), "₹ crore a month")]),
        title="Who earns the fee (₹ crore a month)", subtitle="Split as reported in the press: 40 / 30 / 20 / 10")
    p.add("appFee", 800, CHART_Y, 464, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(M("Est. App MDR Income Cr (Month)"), "Descending"), labels=True,
        Category=[fcol("DimApp", "App")], Y=[(M("Est. App MDR Income Cr (Month)"), "₹ crore a month")]),
        title="UPI apps' share of the fee (₹ crore a month)", subtitle="Estimate: apps' 20% pool split by share of UPI value")
    pages.append(p)

    # 6 Bank reliability -------------------------------------------------------------------------
    p = Page("p6_banks", "Bank Reliability")
    page_header(p, "Bank Reliability  ·  Which banks fail their customers?")
    headline_strip(p, "Bank Headline")
    kpi_row(p, [
        ("Approval Rate % (Month)", "Payments approved", "Sub Approval", "Color Approval", 24),
        ("Business Decline % (Month)", "Business declines", "Sub BD", "Color BD", 24),
        ("Technical Decline % (Month)", "Technical declines", "Sub TD", "Color TD", 24),
        ("Failed Payments Mn (Month)", "Failed payments (mn)", "Sub Failed", "Color Neutral", 24),
        ("Lowest Approval Bank Name (Month)", "Lowest approval rate", "Sub Lowest Approval", "Color Neutral", 15),
    ])
    p.add("approval", 16, CHART_Y, 420, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(M("Bottom 15 Approval Rate % (Month)"), "Ascending"), labels=True,
        color_measure="Color Bank Type",
        Category=[fcol("DimBank", "Bank")], Y=[(M("Bottom 15 Approval Rate % (Month)"), "Approval rate")]),
        title="15 lowest approval rates (of the top 20 banks)", subtitle="Colour = bank type. Click a bar to see its trend.")
    p.add("scatter", 448, CHART_Y, 416, BOTTOM - CHART_Y, chart(
        "scatterChart", legend="Top",
        Category=[fcol("DimBank", "Bank")], Series=[fcol("DimBank", "Bank Type")],
        X=[(M("Bank Volume Mn (Month)"), "Payments sent (mn)")], Y=[(M("Approval Rate % (Month)"), "Approval rate")]),
        title="Size vs reliability", subtitle="Payments banks have the lowest approval rates")
    half = (BOTTOM - CHART_Y - 12) // 2
    p.add("trendType", 876, CHART_Y, 388, half, chart(
        "lineChart", legend="Top",
        Category=[D("Date")], Series=[fcol("DimBank", "Bank Type")], Y=[(M("Approval Rate %"), "Approval rate")]),
        title="Approval rate over time", subtitle="By bank type, or for the bank you click")
    p.add("bankTbl", 876, CHART_Y + half + 12, 388, half, table(
        [(fcol("DimBank", "Bank"), "Bank"), (M("Bank Volume Mn (Month)"), "Sent (mn)"),
         (M("Approval Rate % (Month)"), "Approved"), (M("Business Decline % (Month)"), "BD"),
         (M("Technical Decline % (Month)"), "TD")],
        [110, 56, 70, 54, 50],
        sort=(M("Bank Volume Mn (Month)"), "Descending")),
        title="Bank scorecard", subtitle="BD = business decline, TD = technical decline")
    p.no_filter_from_slicer = ["trendType"]
    pages.append(p)

    # 7 States -----------------------------------------------------------------------------------
    p = Page("p7_states", "State-wise Adoption")
    page_header(p, "State-wise Adoption  ·  Where is UPI used?")
    headline_strip(p, "Geography Headline")
    kpi_row(p, [
        ("Top State (Month)", "Top state", "Sub Top State", "Color Neutral", 18),
        ("Top 5 States Share % (Month)", "Top 5 states' share", "Sub Top 5", "Color Neutral", 24),
        ("Located Volume Bn (Month)", "Payments with a state tag (bn)", "Sub Located", "Color Located", 24),
        ("Highest Avg Payment State (Month)", "Highest average payment", "Sub Highest Avg", "Color Neutral", 18),
        ("Unclassified Share % (Month)", "No state tag", "Sub Unclassified", "Color Neutral", 24),
    ])
    p.add("states", 16, CHART_Y, 420, BOTTOM - CHART_Y, chart(
        "clusteredBarChart", sort=(M("Top 15 State Volume Mn (Month)"), "Descending"), labels=True,
        Category=[fcol("DimState", "State Name")], Y=[(M("Top 15 State Volume Mn (Month)"), "Transactions (mn)")]),
        title="Top 15 states by transactions (mn)", subtitle="Click a state to filter the page")
    half = (BOTTOM - CHART_Y - 12) // 2
    region_h = 150
    p.add("regions", 448, CHART_Y, 400, region_h, chart(
        "clusteredColumnChart", sort=(M("Located Volume Mn (Month)"), "Descending"), labels=True,
        Category=[fcol("DimState", "Region")], Y=[(M("Located Volume Mn (Month)"), "Transactions (mn)")]),
        title="Transactions by region (mn)")
    p.add("avgState", 448, CHART_Y + region_h + 12, 400, BOTTOM - CHART_Y - region_h - 12, chart(
        "clusteredBarChart", sort=(M("Top 10 State Avg Ticket ₹ (Month)"), "Descending"), labels=True,
        Category=[fcol("DimState", "State Name")], Y=[(M("Top 10 State Avg Ticket ₹ (Month)"), "Average payment (₹)")]),
        title="Average payment (₹), 10 biggest states")
    p.add("stateTbl", 860, CHART_Y, 404, BOTTOM - CHART_Y, table(
        [(fcol("DimState", "State Name"), "State"), (M("Located Volume Mn (Month)"), "Payments (mn)"),
         (M("State Share of Located %"), "Share"), (M("State Avg Ticket ₹ (Month)"), "Avg payment"),
         (M("State YoY % (Month)"), "Growth")],
        [120, 72, 52, 70, 56],
        sort=(M("Located Volume Mn (Month)"), "Descending"),
        font_color_rules=[(M("State YoY % (Month)"), "Color State Growth")]),
        title="State scorecard", subtitle="Growth: green = up, red = down vs the same month last year")
    pages.append(p)

    # 8 About ------------------------------------------------------------------------------------
    p = Page("p8_about", "About the Data")
    page_header(p, "About the Data  ·  Sources, method and definitions", month_slicer=False)
    H = lambda t: para(run(t, 12, True, INK))
    T = lambda t: para(run(t, 10))
    box = {"background": [{"properties": {"show": b(True), "color": color(WHITE), "transparency": d(0)}}]}
    p.add("aboutL", 16, STRIP_Y, 616, BOTTOM - STRIP_Y, textbox([
        H("Business questions"),
        T("1. How fast is UPI growing, and is it becoming an everyday small-payments network?"),
        T("2. Who controls the market, and can PhonePe and Google Pay meet NPCI's 30% market-share cap?"),
        T("3. Where do people spend through UPI?"),
        T("4. What will NPCI's new 0.4% merchant fee (MDR) earn, and who gets the money?"),
        T("5. Which banks fail their customers most often, and why?"),
        T("6. Which states drive UPI usage?"),
        T(" "),
        H("Data sources"),
        T("NPCI Product Statistics (npci.org.in): monthly UPI volume, value and banks live, April 2016 to August 2026."),
        T("NPCI Ecosystem Statistics: UPI apps (April 2023+), P2P vs P2M (April 2020+), merchant categories (April 2024+), "
          "states and districts (April 2025+), top remitter banks' approval and decline rates (April 2025+)."),
        T("MDR rules: NPCI FAQ of 15 Sep 2026. The 67% high-value share (RetailIntel) and the 40/30/20/10 revenue "
          "split (IBTimes, 25 Sep 2026) are press figures, so the simulator lets you change the assumptions."),
        T("The 30% market-share cap deadline (31 Dec 2026) is as last extended by NPCI in December 2024."),
        T(" "),
        H("How it was built"),
        T("Power Query: 10 queries parse the NPCI CSVs (embedded in the file so it refreshes on any computer), set types, "
          "turn month names into dates, unpivot P2P/P2M, standardise bank names and sum districts to states."),
        T("Data model: star schema. Six fact tables share a monthly DimDate with the Indian fiscal year (April-March); "
          "dimensions for apps, banks, states and merchant categories; four what-if tables drive the MDR simulator."),
        T(f"DAX: {len(MEASURES)} measures: month-selected KPIs, same-month-last-year growth, market share, HHI concentration, "
          "Top-N ranking, volume-weighted decline rates, a 30 bn projection, what-if revenue, dynamic text and "
          "conditional-formatting colours."),
    ]), container=box)
    p.add("aboutR", 648, STRIP_Y, 616, BOTTOM - STRIP_Y, textbox([
        H("How to use"),
        T("The Month slicer (top right, synced across pages) opens on the latest month. Pick another month to change "
          "every KPI, ranking and sentence. Trend charts always show full history."),
        T("Click a bar or dot to cross-filter the page. On the MDR page, change the three assumptions; the first "
          "option in each is the NPCI or reported value."),
        T(" "),
        H("Definitions"),
        T("Volume: number of transactions (millions). Value: rupees crore (1 crore = 10 million; 1 lakh crore = 1 trillion)."),
        T("P2P: person-to-person transfer. P2M: person-to-merchant (shop) payment."),
        T("MDR: merchant discount rate, the fee a merchant pays on a digital payment."),
        T("HHI: Herfindahl-Hirschman Index, the sum of squared market shares. Above 2,500 means highly concentrated."),
        T("Business decline (BD): failed because of the customer or rules (wrong PIN, balance, limits). "
          "Technical decline (TD): failed because of a bank or NPCI system problem."),
        T("30 bn projection: months until 30 bn transactions a month if the latest year-on-year growth rate continues."),
        T(" "),
        H("Limitations"),
        T("NPCI publishes monthly totals, not individual transactions, so this is market-level analysis."),
        T("App data groups the long tail of small apps into 'Others'. Bank data covers the 20 largest sending banks."),
        T("About 44% of transactions carry no state tag, so state shares use located volume only."),
        T("MDR revenue is an estimate: NPCI does not publish merchant value by ticket size, and caps, flat fees and "
          "exemptions reduce the real figure (use slicer 3)."),
    ]), container=box)
    pages.append(p)
    return pages


THEME = {
    "name": "UPI Market Intelligence",
    "dataColors": [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED],
    "foreground": INK,
    "foregroundNeutralSecondary": INK2,
    "foregroundNeutralTertiary": MUTED,
    "background": WHITE,
    "backgroundLight": PAGE_BG,
    "backgroundNeutral": "#D5DAE8",
    "tableAccent": NAVY,
    "good": GOOD,
    "neutral": YELLOW,
    "bad": BAD,
    "maximum": BLUE,
    "center": "#9EC5F4",
    "minimum": "#EAF2FC",
    "textClasses": {
        "callout": {"fontSize": 24, "fontFace": "Segoe UI Semibold", "color": INK},
        "title": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
        "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
        "label": {"fontSize": 9, "fontFace": "Segoe UI", "color": INK2},
    },
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": WHITE}}, "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": TILE_BORDER}}, "radius": 8}],
            "dropShadow": [{"show": False}],
            "title": [{"show": True, "fontColor": {"solid": {"color": INK}}, "fontSize": 11, "fontFamily": "Segoe UI Semibold"}],
            "subTitle": [{"fontColor": {"solid": {"color": INK2}}, "fontSize": 9}],
            "padding": [{"top": 8, "bottom": 8, "left": 10, "right": 10}],
            "visualHeader": [{"show": True}],
            "valueAxis": [{"gridlineColor": {"solid": {"color": "#E8EBF2"}}, "labelColor": {"solid": {"color": INK2}},
                           "fontSize": 8, "showAxisTitle": False}],
            "categoryAxis": [{"labelColor": {"solid": {"color": INK2}}, "fontSize": 8, "showAxisTitle": False}],
        }},
        "page": {"*": {
            "background": [{"color": {"solid": {"color": PAGE_BG}}, "transparency": 0}],
            "outspace": [{"color": {"solid": {"color": "#E9ECF5"}}, "transparency": 0}],
        }},
        "card": {"*": {
            "labels": [{"color": {"solid": {"color": INK}}, "fontSize": 24}],
            "categoryLabels": [{"show": False}],
            "title": [{"fontColor": {"solid": {"color": INK2}}, "fontSize": 10, "fontFamily": "Segoe UI"}],
        }},
        "slicer": {"*": {"items": [{"fontColor": {"solid": {"color": INK}}}]}},
        "lineChart": {"*": {"lineStyles": [{"strokeWidth": 2}]}},
        "areaChart": {"*": {"lineStyles": [{"strokeWidth": 2}]}},
    },
}


def build_report(pages):
    defn = RP / "definition"
    write_json(RP / "definition.pbir", {
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    })
    write_json(RP / ".platform", {
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": guid("logical:report")},
    })
    theme_name = "UPIMarketTheme.json"
    write_json(RP / "StaticResources" / "RegisteredResources" / theme_name, THEME)
    base_theme = "CY26SU07"
    base_dst = RP / "StaticResources" / "SharedResources" / "BaseThemes" / f"{base_theme}.json"
    base_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / f"{base_theme}.json", base_dst)
    version_at_import = {"visual": V_VISUAL, "page": V_PAGE, "report": V_REPORT}
    write_json(defn / "version.json", {
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })
    write_json(defn / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/{V_REPORT}/schema.json",
        "themeCollection": {
            "baseTheme": {"name": base_theme, "reportVersionAtImport": version_at_import, "type": "SharedResources"},
            "customTheme": {"name": theme_name, "reportVersionAtImport": version_at_import, "type": "RegisteredResources"},
        },
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": base_theme, "path": f"BaseThemes/{base_theme}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": theme_name, "path": theme_name, "type": "CustomTheme"}]},
        ],
        "objects": {"section": [{"properties": {"verticalAlignment": s("Top")}}]},
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "useEnhancedTooltips": True,
        },
    })
    write_json(defn / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages],
        "activePageName": pages[0].name,
    })
    for p in pages:
        pj = {
            "$schema": f"{SCHEMA}/item/report/definition/page/{V_PAGE}/schema.json",
            "name": p.name,
            "displayName": p.display,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        }
        if p.no_filter_from_slicer:
            pj["visualInteractions"] = [{"source": "month", "target": t, "type": "NoFilter"} for t in p.no_filter_from_slicer]
        write_json(defn / "pages" / p.name / "page.json", pj)
        for v in p.visuals:
            write_json(defn / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)


def main():
    for folder in (SM, RP):
        if folder.exists():
            shutil.rmtree(folder)
    build_model()
    pages = build_pages()
    build_report(pages)
    write_json(ROOT / f"{NAME}.pbip", {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    print(f"Built {NAME}: {len(MEASURES)} measures, {len(pages)} pages, {sum(len(p.visuals) for p in pages)} visuals")


if __name__ == "__main__":
    main()
