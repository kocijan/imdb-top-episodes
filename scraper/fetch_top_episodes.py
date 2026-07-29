"""
TopEpisode.com - data builder.

Outputs a CSV file (sorted by episode_id for stable diffs) containing the top-
rated TV episodes by IMDb user rating.

Primary path: IMDb's unofficial internal GraphQL API (api.graphql.imdb.com),
the same endpoint imdb.com's own "Advanced Title Search" page
(https://www.imdb.com/search/title/?title_type=tv_episode&num_votes=1000,&sort=user_rating,desc)
calls in the browser. It requires no API key/auth and supports cursor-based
pagination up to 250 items per page via `advancedTitleSearch`.

This is UNDOCUMENTED and may break or get rate-limited without notice, so
this script falls back automatically to IMDb's official, free,
non-commercial dataset dumps (datasets.imdbws.com) if the GraphQL calls
fail after retries. See README.md for details and IMDb's non-commercial
data terms: https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX

For each qualifying episode we also compute:
  - total_binge_seconds: sum of runtimes for ALL episodes of the parent
    series (i.e. how long it takes to watch the entire show).
  - watch_to_here_seconds: sum of runtimes from S01E01 up to and including
    this episode (in season/episode order), i.e. how long it takes to
    reach this episode from the start of the show.

Output: data/top_episodes.csv
"""
import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
import re

import requests

GRAPHQL_URL = "https://api.graphql.imdb.com/"
DATASETS_BASE = "https://datasets.imdbws.com"
MIN_VOTES = int(os.environ.get("MIN_VOTES", "100"))
TOP_N = int(os.environ.get("TOP_N", "10000"))
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "data/top_episodes.csv")

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; AbsoluteCinemaTV/1.0; +https://github.com/kocijan/imdb-top-episodes)",
}

TOP_EPISODES_QUERY = """
query TopEpisodes($first: Int!, $after: String, $minVotes: Int!) {
  advancedTitleSearch(
    first: $first
    after: $after
    constraints: {
      titleTypeConstraint: { anyTitleTypeIds: ["tvEpisode"] }
      userRatingsConstraint: { ratingsCountRange: { min: $minVotes } }
    }
    sort: { sortBy: USER_RATING, sortOrder: DESC }
  ) {
    total
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        title {
          id
          titleText { text }
          releaseYear { year }
          runtime { seconds }
          ratingsSummary { aggregateRating voteCount }
          series {
            series { id titleText { text } }
            episodeNumber { episodeNumber seasonNumber }
          }
        }
      }
    }
  }
}
"""

SERIES_EPISODES_QUERY = """
query SeriesEpisodes($id: ID!, $first: Int!, $after: ID) {
  title(id: $id) {
    episodes {
      episodes(first: $first, after: $after) {
        total
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            runtime { seconds }
            series { episodeNumber { episodeNumber seasonNumber } }
          }
        }
      }
    }
  }
}
"""


def gql(query, variables, max_retries=4):
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                GRAPHQL_URL,
                headers=HEADERS,
                json={"query": query, "variables": variables},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body and not body.get("data"):
                raise RuntimeError(f"GraphQL errors: {body['errors']}")
            return body["data"]
        except Exception as e:
            last_err = e
            print(f"  GraphQL attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GraphQL request failed after {max_retries} attempts: {last_err}")


def fetch_top_episodes_via_graphql(min_votes: int, top_n: int):
    if top_n > 10000:
        raise RuntimeError(f"GraphQL Advanced Title Search has a hard pagination limit of 10000 results. Cannot fetch {top_n} episodes via GraphQL.")
        
    episodes = []
    after = None
    while len(episodes) < top_n:
        page_size = min(250, top_n - len(episodes))
        data = gql(
            TOP_EPISODES_QUERY,
            {"first": page_size, "after": after, "minVotes": min_votes},
        )
        result = data["advancedTitleSearch"]
        for edge in result["edges"]:
            node = edge["node"]["title"]
            series = node.get("series") or {}
            series_title_obj = series.get("series") or {}
            ep_num_obj = series.get("episodeNumber") or {}
            rating_obj = node.get("ratingsSummary") or {}
            runtime_obj = node.get("runtime") or {}
            year_obj = node.get("releaseYear") or {}

            episodes.append(
                {
                    "episode_id": node["id"],
                    "episode_title": (node.get("titleText") or {}).get("text"),
                    "year": year_obj.get("year"),
                    "runtime_seconds": runtime_obj.get("seconds"),
                    "rating": rating_obj.get("aggregateRating"),
                    "votes": rating_obj.get("voteCount"),
                    "series_id": series_title_obj.get("id"),
                    "series_title": (series_title_obj.get("titleText") or {}).get("text"),
                    "season_number": ep_num_obj.get("seasonNumber"),
                    "episode_number": ep_num_obj.get("episodeNumber"),
                }
            )
        page_info = result["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]
        time.sleep(0.4)
    return episodes[:top_n]


def fetch_series_runtimes_via_graphql(series_id: str):
    """Returns list of (season, episode_number, runtime_seconds) for every
    episode of a series, using the GraphQL API."""
    all_eps = []
    after = None
    while True:
        data = gql(
            SERIES_EPISODES_QUERY,
            {"id": series_id, "first": 100, "after": after},
        )
        title = data.get("title")
        if not title or not title.get("episodes"):
            break
        conn = title["episodes"]["episodes"]
        for edge in conn["edges"]:
            node = edge["node"]
            ep_num_obj = (node.get("series") or {}).get("episodeNumber") or {}
            runtime_obj = node.get("runtime") or {}
            all_eps.append(
                {
                    "episode_id": node["id"],
                    "season_number": ep_num_obj.get("seasonNumber"),
                    "episode_number": ep_num_obj.get("episodeNumber"),
                    "runtime_seconds": runtime_obj.get("seconds"),
                }
            )
        page_info = conn["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]
        time.sleep(0.3)
    return all_eps


def download_tsv(name: str, use_cache=False, keep_cache=False):
    """Download an IMDb TSV dataset, with optional local caching.

    Args:
        name: Filename like 'title.basics.tsv.gz'.
        use_cache: If True, use a previously cached file instead of re-downloading.
        keep_cache: If True, save the download to data/cache/ for future use.
    """
    import pandas as pd

    cache_dir = os.path.join("data", "cache")
    cache_path = os.path.join(cache_dir, name)

    if use_cache and os.path.isfile(cache_path):
        print(f"[fallback] Using cached {cache_path}", file=sys.stderr)
        with gzip.open(cache_path, "rt", encoding="utf-8") as gz:
            df = pd.read_csv(gz, sep="\t", low_memory=False, na_values=["\\N"])
        return df

    url = f"{DATASETS_BASE}/{name}"
    print(f"[fallback] Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    raw = resp.content

    if keep_cache:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(raw)
        print(f"[fallback] Cached to {cache_path}", file=sys.stderr)

    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        df = pd.read_csv(gz, sep="\t", low_memory=False, na_values=["\\N"])
    return df


def fetch_via_dataset_fallback(min_votes: int, top_n: int, use_cache=False, keep_cache=False):
    """Fallback path using IMDb's official non-commercial dataset dumps.
    Used only if the GraphQL API is unavailable.

    Returns:
        (episodes_list, basics_df, episode_df): the top episodes as dicts,
        plus the raw DataFrames needed for binge-time computation.
    """
    import pandas as pd

    basics = download_tsv("title.basics.tsv.gz", use_cache=use_cache, keep_cache=keep_cache)
    ratings = download_tsv("title.ratings.tsv.gz", use_cache=use_cache, keep_cache=keep_cache)
    episode_df = download_tsv("title.episode.tsv.gz", use_cache=use_cache, keep_cache=keep_cache)

    episodes = basics[basics["titleType"] == "tvEpisode"].copy()
    episodes = episodes.merge(episode_df, on="tconst", how="inner")
    episodes = episodes.merge(ratings, on="tconst", how="inner")
    episodes["numVotes"] = pd.to_numeric(episodes["numVotes"], errors="coerce")
    episodes = episodes[episodes["numVotes"] >= min_votes]

    series_ids = episodes["parentTconst"].unique().tolist()
    series_info = basics[basics["tconst"].isin(series_ids)][
        ["tconst", "primaryTitle"]
    ].rename(columns={"tconst": "parentTconst", "primaryTitle": "seriesTitle"})

    episodes = episodes.merge(series_info, on="parentTconst", how="left")
    episodes["averageRating"] = pd.to_numeric(episodes["averageRating"], errors="coerce")
    episodes = episodes.sort_values(
        ["averageRating", "numVotes"], ascending=[False, False]
    ).head(top_n)

    results = []
    for _, row in episodes.iterrows():
        runtime_min = row.get("runtimeMinutes")
        results.append(
            {
                "episode_id": row["tconst"],
                "episode_title": row.get("primaryTitle"),
                "year": int(row["startYear"]) if pd.notna(row.get("startYear")) else None,
                "runtime_seconds": int(float(runtime_min) * 60) if pd.notna(runtime_min) else None,
                "rating": float(row["averageRating"]),
                "votes": int(row["numVotes"]),
                "series_id": row["parentTconst"],
                "series_title": row.get("seriesTitle"),
                "season_number": int(row["seasonNumber"]) if pd.notna(row.get("seasonNumber")) else None,
                "episode_number": int(row["episodeNumber"]) if pd.notna(row.get("episodeNumber")) else None,
            }
        )
    return results, basics, episode_df


def compute_binge_times(episodes):
    """Given the flat list of top episodes, fetch each parent series' full
    episode list (GraphQL) and compute total_binge_seconds and
    watch_to_here_seconds for every episode."""
    return episodes
    series_ids = sorted({e["series_id"] for e in episodes if e.get("series_id")})
    series_runtime_cache = {}

    for i, sid in enumerate(series_ids):
        try:
            eps = fetch_series_runtimes_via_graphql(sid)
        except Exception as e:
            print(f"  Failed to fetch episodes for series {sid}: {e}", file=sys.stderr)
            eps = []
        series_runtime_cache[sid] = eps
        print(f"  [{i + 1}/{len(series_ids)}] {sid}: {len(eps)} episodes", file=sys.stderr)
        time.sleep(0.2)

    for ep in episodes:
        sid = ep.get("series_id")
        series_eps = series_runtime_cache.get(sid, [])
        if not series_eps:
            ep["total_binge_seconds"] = None
            ep["watch_to_here_seconds"] = None
            continue

        runtimes = [se.get("runtime_seconds") for se in series_eps if se.get("runtime_seconds")]
        avg_runtime = (sum(runtimes) / len(runtimes)) if runtimes else (ep.get("runtime_seconds") or 0)

        total = 0
        for se in series_eps:
            total += se.get("runtime_seconds") or avg_runtime
        ep["total_binge_seconds"] = float(total)

        def sort_key(se):
            s = se.get("season_number")
            e = se.get("episode_number")
            return (s if s is not None else 9999, e if e is not None else 9999)

        ordered = sorted(series_eps, key=sort_key)
        cumulative = 0.0
        watch_to_here = None
        for se in ordered:
            cumulative += se.get("runtime_seconds") or avg_runtime
            if se["episode_id"] == ep["episode_id"]:
                watch_to_here = cumulative
                break
        ep["watch_to_here_seconds"] = watch_to_here if watch_to_here is not None else ep.get("runtime_seconds")

    return episodes


CSV_FIELDS = [
    "episode_id", "episode_title", "year", "runtime_seconds",
    "rating", "votes", "series_id", "series_title",
    "season_number", "episode_number",
    "total_binge_seconds", "watch_to_here_seconds",
]


def compute_binge_times_from_datasets(episodes, basics_df, episode_df):
    """Compute total_binge_seconds and watch_to_here_seconds for every
    episode using the already-loaded IMDb dataset DataFrames.

    This is the dataset-fallback equivalent of compute_binge_times() which
    uses GraphQL. The data needed is already in basics (runtimeMinutes) and
    episode_df (parentTconst, seasonNumber, episodeNumber).
    """
    import pandas as pd

    series_ids = sorted({e["series_id"] for e in episodes if e.get("series_id")})
    if not series_ids:
        for ep in episodes:
            ep["total_binge_seconds"] = None
            ep["watch_to_here_seconds"] = None
        return episodes

    print(f"  Computing binge times for {len(series_ids)} unique series...", file=sys.stderr)

    # Get all episodes belonging to the relevant series
    sibling_eps = episode_df[episode_df["parentTconst"].isin(series_ids)].copy()
    # Join with basics to get runtimes
    sibling_eps = sibling_eps.merge(
        basics_df[["tconst", "runtimeMinutes"]],
        on="tconst",
        how="left",
    )
    sibling_eps["runtimeMinutes"] = pd.to_numeric(sibling_eps["runtimeMinutes"], errors="coerce")
    sibling_eps["runtime_sec"] = sibling_eps["runtimeMinutes"] * 60
    sibling_eps["seasonNumber"] = pd.to_numeric(sibling_eps["seasonNumber"], errors="coerce")
    sibling_eps["episodeNumber"] = pd.to_numeric(sibling_eps["episodeNumber"], errors="coerce")

    # Pre-compute per-series data: total binge and ordered episode list
    series_cache = {}
    for sid in series_ids:
        ser_eps = sibling_eps[sibling_eps["parentTconst"] == sid].copy()
        runtimes = ser_eps["runtime_sec"].dropna()
        avg_runtime = runtimes.mean() if len(runtimes) > 0 else 0

        # Fill missing runtimes with average
        ser_eps["runtime_filled"] = ser_eps["runtime_sec"].fillna(avg_runtime)

        total_binge = ser_eps["runtime_filled"].sum()

        # Sort by season, episode for watch_to_here
        ser_eps = ser_eps.sort_values(
            ["seasonNumber", "episodeNumber"],
            ascending=[True, True],
            na_position="last",
        )
        ser_eps["cumulative"] = ser_eps["runtime_filled"].cumsum()

        # Build lookup: episode_id -> cumulative runtime
        watch_lookup = dict(zip(ser_eps["tconst"], ser_eps["cumulative"]))

        series_cache[sid] = {
            "total_binge": float(total_binge),
            "watch_lookup": watch_lookup,
        }

    # Apply to each episode
    for ep in episodes:
        sid = ep.get("series_id")
        cache = series_cache.get(sid)
        if not cache:
            ep["total_binge_seconds"] = None
            ep["watch_to_here_seconds"] = None
            continue

        ep["total_binge_seconds"] = cache["total_binge"]
        wth = cache["watch_lookup"].get(ep["episode_id"])
        ep["watch_to_here_seconds"] = float(wth) if wth is not None else ep.get("runtime_seconds")

    return episodes


def parse_args():
    parser = argparse.ArgumentParser(description="TopEpisode.com data builder")
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="Save downloaded IMDb dataset files to data/cache/ for future use",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use previously cached IMDb dataset files instead of re-downloading",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    used_fallback = False
    basics_df = None
    episode_df = None

    try:
        print(f"Fetching top {TOP_N} episodes (min {MIN_VOTES} votes) via GraphQL...", file=sys.stderr)
        episodes = fetch_top_episodes_via_graphql(MIN_VOTES, TOP_N)
        if not episodes:
            raise RuntimeError("GraphQL returned zero episodes")
    except Exception as e:
        print(f"GraphQL primary path failed: {e}", file=sys.stderr)
        print("Falling back to IMDb non-commercial dataset dumps...", file=sys.stderr)
        episodes, basics_df, episode_df = fetch_via_dataset_fallback(
            MIN_VOTES, TOP_N,
            use_cache=args.use_cache,
            keep_cache=args.keep_cache,
        )
        used_fallback = True

    if not episodes:
        print("ERROR: no episodes fetched from either source, aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"Computing binge-watch times for {len(episodes)} episodes...", file=sys.stderr)
    if used_fallback and basics_df is not None and episode_df is not None:
        episodes = compute_binge_times_from_datasets(episodes, basics_df, episode_df)
    elif not used_fallback:
        episodes = compute_binge_times(episodes)
    else:
        for ep in episodes:
            ep["total_binge_seconds"] = None
            ep["watch_to_here_seconds"] = None

    # Sort by episode_id for stable, minimal git diffs
    episodes.sort(key=lambda e: e["episode_id"])

    out_dir = os.path.dirname(OUTPUT_PATH) or "."
    os.makedirs(out_dir, exist_ok=True)

    chunks = {
        "90_1000": [],
        "90_100": [],
        "85_1000": [],
        "85_100": [],
        "80_1000": [],
        "80_100": [],
        "0_1000": [],
        "0_100": []
    }

    for ep in episodes:
        r = ep.get("rating") or 0.0
        v = ep.get("votes") or 0
        if r >= 9.0:
            if v >= 1000: chunks["90_1000"].append(ep)
            else: chunks["90_100"].append(ep)
        elif r >= 8.5:
            if v >= 1000: chunks["85_1000"].append(ep)
            else: chunks["85_100"].append(ep)
        elif r >= 8.0:
            if v >= 1000: chunks["80_1000"].append(ep)
            else: chunks["80_100"].append(ep)
        else:
            if v >= 1000: chunks["0_1000"].append(ep)
            else: chunks["0_100"].append(ep)

    for name, chunk_eps in chunks.items():
        chunk_path = os.path.join(out_dir, f"top_episodes_{name}.csv")
        with open(chunk_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)
            for ep in chunk_eps:
                writer.writerow(ep.get(field, "") if ep.get(field) is not None else "" for field in CSV_FIELDS)
        print(f"Wrote {len(chunk_eps)} episodes to {chunk_path}", file=sys.stderr)

    # Inject top 100 episodes into index.html for instant rendering
    top_100_chunk = list(chunks.get("90_1000", []))
    # Sort by Rating (desc), then Votes (desc)
    top_100_chunk.sort(key=lambda e: (e.get("rating") or 0.0, e.get("votes") or 0), reverse=True)
    top_100 = top_100_chunk[:100]
    
    template_path = os.path.join(out_dir, "..", "site", "template.html")
    index_path = os.path.join(out_dir, "..", "site", "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        json_data = json.dumps(top_100, separators=(',', ':'))
        content = re.sub(
            r"/\* DATA_START \*/.*?/\* DATA_END \*/",
            lambda m: f"/* DATA_START */ {json_data} /* DATA_END */",
            content,
            flags=re.DOTALL
        )
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Generated {index_path} from template", file=sys.stderr)

    # Clean up cache if not keeping it
    if not args.keep_cache:
        cache_dir = os.path.join("data", "cache")
        if os.path.isdir(cache_dir):
            import shutil
            shutil.rmtree(cache_dir)
            print(f"Cleaned up cache directory {cache_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()

