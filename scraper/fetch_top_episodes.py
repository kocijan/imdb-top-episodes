"""
Absolute Cinema TV Episodes - data builder.

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
import csv
import gzip
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

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


def download_tsv(name: str):
    import pandas as pd

    url = f"{DATASETS_BASE}/{name}"
    print(f"[fallback] Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
        df = pd.read_csv(gz, sep="\t", low_memory=False, na_values=["\\N"])
    return df


def fetch_via_dataset_fallback(min_votes: int, top_n: int):
    """Fallback path using IMDb's official non-commercial dataset dumps.
    Used only if the GraphQL API is unavailable."""
    import pandas as pd

    basics = download_tsv("title.basics.tsv.gz")
    ratings = download_tsv("title.ratings.tsv.gz")
    episode = download_tsv("title.episode.tsv.gz")

    episodes = basics[basics["titleType"] == "tvEpisode"].copy()
    episodes = episodes.merge(episode, on="tconst", how="inner")
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
    return results


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


def main():
    used_fallback = False
    try:
        print(f"Fetching top {TOP_N} episodes (min {MIN_VOTES} votes) via GraphQL...", file=sys.stderr)
        episodes = fetch_top_episodes_via_graphql(MIN_VOTES, TOP_N)
        if not episodes:
            raise RuntimeError("GraphQL returned zero episodes")
    except Exception as e:
        print(f"GraphQL primary path failed: {e}", file=sys.stderr)
        print("Falling back to IMDb non-commercial dataset dumps...", file=sys.stderr)
        episodes = fetch_via_dataset_fallback(MIN_VOTES, TOP_N)
        used_fallback = True

    if not episodes:
        print("ERROR: no episodes fetched from either source, aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"Computing binge-watch times for {len(episodes)} episodes...", file=sys.stderr)
    if not used_fallback:
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


if __name__ == "__main__":
    main()

