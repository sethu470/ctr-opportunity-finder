#!/usr/bin/env python3
"""
CTR Opportunity Finder
----------------------
Finds pages / queries that rank on or near page 1 but get fewer clicks than
their position would normally earn, and ranks them by estimated extra clicks.

Input (pick one):
  1. A Google Search Console Performance export (CSV), via --input
  2. The Search Console API (service account), via --site and --creds

Output: a ranked CSV plus a short summary in the terminal.

The numbers are ESTIMATES. They show where to look first, not guaranteed gains.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Rough fallback CTR by position, used only when your own data has too few rows
# at a position to build a benchmark. These are approximations, not a standard.
GENERIC_CTR = {
    1: 0.28, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.055, 6: 0.04, 7: 0.033,
    8: 0.027, 9: 0.023, 10: 0.020, 11: 0.012, 12: 0.010, 13: 0.009,
    14: 0.008, 15: 0.007,
}
FALLBACK_CTR = 0.005

COLUMN_ALIASES = {
    "top pages": "page", "pages": "page", "page": "page",
    "top queries": "query", "queries": "query", "query": "query",
    "clicks": "clicks", "impressions": "impressions",
    "ctr": "ctr", "position": "position",
}


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [COLUMN_ALIASES.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
    needed = {"clicks", "impressions", "position"}
    missing = needed - set(df.columns)
    if missing:
        sys.exit(f"CSV is missing columns: {', '.join(sorted(missing))}. "
                 "Use a Performance export that includes Clicks, Impressions and Position.")
    if "page" not in df.columns and "query" not in df.columns:
        sys.exit("CSV needs a 'Top pages' or 'Top queries' column.")
    return df


def fetch_api(site: str, creds_path: str, days: int, dims: list) -> pd.DataFrame:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("API mode needs: pip install google-api-python-client google-auth")

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds)

    end = date.today() - timedelta(days=3)  # GSC data lags by a couple of days
    start = end - timedelta(days=days)

    rows, start_row, page_size = [], 0, 25000
    while True:
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dims,
            "rowLimit": page_size,
            "startRow": start_row,
        }
        resp = service.searchanalytics().query(siteUrl=site, body=body).execute()
        batch = resp.get("rows", [])
        for r in batch:
            rec = dict(zip(dims, r["keys"]))
            rec.update(clicks=r["clicks"], impressions=r["impressions"], position=r["position"])
            rows.append(rec)
        if len(batch) < page_size:
            break
        start_row += page_size
    return pd.DataFrame(rows)


def clean(df: pd.DataFrame, brand_terms: list) -> pd.DataFrame:
    for col in ("clicks", "impressions", "position"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["clicks", "impressions", "position"])
    df = df[df["impressions"] > 0].copy()
    df["ctr"] = df["clicks"] / df["impressions"]  # recompute for precision

    if brand_terms and "query" in df.columns:
        pattern = "|".join(t.lower() for t in brand_terms)
        df = df[~df["query"].str.lower().str.contains(pattern, na=False, regex=True)]
    return df


def add_benchmark(df: pd.DataFrame, quantile: float, min_rows: int, min_impr: int) -> pd.DataFrame:
    """Expected CTR per position bucket, taken from the site's own data when possible."""
    df = df.copy()
    df["pos_bucket"] = df["position"].round().clip(1, 20).astype(int)

    base = df[df["impressions"] >= min_impr]
    site_ctr = {}
    for bucket, grp in base.groupby("pos_bucket"):
        if len(grp) >= min_rows:
            site_ctr[bucket] = grp["ctr"].quantile(quantile)

    df["expected_ctr"] = df["pos_bucket"].map(
        lambda b: site_ctr.get(b, GENERIC_CTR.get(b, FALLBACK_CTR))
    )
    df["benchmark"] = df["pos_bucket"].map(
        lambda b: "site data" if b in site_ctr else "generic fallback"
    )
    return df


def suggest_lever(position: float) -> str:
    if position <= 10:
        return "Snippet: rewrite title / meta description"
    return "Ranking: strengthen content / internal links first (CTR gain needs page 1)"


def find_opportunities(df, pos_min, pos_max, min_impr):
    cand = df[
        (df["position"] >= pos_min)
        & (df["position"] <= pos_max)
        & (df["impressions"] >= min_impr)
    ].copy()
    cand["ctr_gap"] = (cand["expected_ctr"] - cand["ctr"]).clip(lower=0)
    cand["est_extra_clicks"] = (cand["impressions"] * cand["ctr_gap"]).round(1)
    cand = cand[cand["est_extra_clicks"] > 0]
    cand["lever"] = cand["position"].apply(suggest_lever)
    return cand.sort_values("est_extra_clicks", ascending=False)


def main():
    p = argparse.ArgumentParser(description="Find pages/queries with below-expected CTR for their position.")
    src = p.add_argument_group("data source (choose one)")
    src.add_argument("--input", help="Search Console Performance export (CSV)")
    src.add_argument("--site", help="Search Console property, e.g. sc-domain:example.com")
    src.add_argument("--creds", help="Service account JSON key (API mode)")
    src.add_argument("--days", type=int, default=90, help="Days of data in API mode (default 90)")
    src.add_argument("--dims", default="page,query", help="API dimensions (default page,query)")

    p.add_argument("--pos-min", type=float, default=4, help="Minimum position (default 4)")
    p.add_argument("--pos-max", type=float, default=15, help="Maximum position (default 15)")
    p.add_argument("--min-impressions", type=int, default=100, help="Ignore rows below this (default 100)")
    p.add_argument("--quantile", type=float, default=0.5,
                   help="Benchmark quantile of your own CTR at each position (default 0.5 = median)")
    p.add_argument("--min-rows", type=int, default=5,
                   help="Rows needed at a position to trust site data (default 5)")
    p.add_argument("--brand-terms", default="", help="Comma-separated brand terms to exclude from queries")
    p.add_argument("--top", type=int, default=25, help="Rows to print (default 25)")
    p.add_argument("--output", default="ctr_opportunities.csv", help="Output CSV path")
    args = p.parse_args()

    if args.input:
        df = load_csv(Path(args.input))
    elif args.site and args.creds:
        df = fetch_api(args.site, args.creds, args.days, [d.strip() for d in args.dims.split(",")])
    else:
        p.error("Provide --input FILE.csv, or --site and --creds for API mode.")

    brand = [t.strip() for t in args.brand_terms.split(",") if t.strip()]
    df = clean(df, brand)
    if df.empty:
        sys.exit("No usable rows after cleaning.")

    df = add_benchmark(df, args.quantile, args.min_rows, args.min_impressions)
    opps = find_opportunities(df, args.pos_min, args.pos_max, args.min_impressions)

    if opps.empty:
        sys.exit("No opportunities found with these filters. Try lowering --min-impressions.")

    keep = [c for c in ("page", "query") if c in opps.columns]
    keep += ["position", "impressions", "clicks", "ctr", "expected_ctr",
             "est_extra_clicks", "lever", "benchmark"]
    out = opps[keep].copy()
    out["position"] = out["position"].round(1)
    out["ctr"] = (out["ctr"] * 100).round(2)
    out["expected_ctr"] = (out["expected_ctr"] * 100).round(2)
    out = out.rename(columns={"ctr": "ctr_%", "expected_ctr": "expected_ctr_%"})
    out.to_csv(args.output, index=False)

    snippet_fixes = opps[opps["position"] <= 10]
    print(f"\nRows analysed: {len(df):,} | Opportunities found: {len(opps):,}")
    print(f"Estimated extra clicks from snippet fixes (positions <=10): "
          f"{snippet_fixes['est_extra_clicks'].sum():,.0f}")
    print(f"Benchmark source mix: {opps['benchmark'].value_counts().to_dict()}\n")
    with pd.option_context("display.max_colwidth", 60, "display.width", 200):
        print(out.head(args.top).to_string(index=False))
    print(f"\nFull results saved to: {args.output}")
    print("Note: figures are estimates for prioritisation, not forecasts.")


if __name__ == "__main__":
    main()
