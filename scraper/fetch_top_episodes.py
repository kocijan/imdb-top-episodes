"""
Absolute Cinema TV Episodes - data builder.

Builds a leaderboard of the highest-rated TV episodes (by IMDb user rating,
filtered by a minimum vote count) using IMDb's official, free, daily-updated
non-commercial datasets:

    https://datasets.imdbws.com/title.basics.tsv.gz
    https://datasets.imdbws.com/title.ratings.tsv.gz
    https://datasets.imdbws.com/title.episode.tsv.gz

This avoids scraping IMDb's website entirely and stays within IMDb's terms
for non-commercial use (see https://developer.imdb.com/non-commercial-datasets/).

For each qualifying episode we also compute:
  - total_binge_seconds: sum of runtimes for ALL episodes of the parent
    series (i.e. how long it takes to watch the entire show).
  - watch_to_here_seconds: sum of runtimes from S01E01 up to and including
    this episode (in air/season order), i.e. how long it takes to reach
    this episode from the start of the show.

Output: data/top_episodes.json
"""
import gzip
import io
import json
import os
import sys
from datetime import datetime, timezone

import requests
import pandas as pd

DATASETS_BASE = "https://datasets.imdbws.com"
MIN_VOTES = int(os.environ.get("MIN_VOTES", "1000"))
TOP_N = int(os.environ.get("TOP_N", "250"))
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "data/top_episodes.json")


def download_tsv(name: str) -> pd.DataFrame:
    url = f"{DATASETS_BASE}/{name}"
    print(f"Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
        df = pd.read_csv(gz, sep="\t", low_memory=False, na_values=["\\N"])
    print(f"  -> {len(df):,} rows", file=sys.stderr)
    return df


def main():
    basics = download_tsv("title.basics.tsv.gz")
    ratings = download_tsv("title.ratings.tsv.gz")
    episode = download_tsv("title.episode.tsv.gz")

    episodes = basics[basics["titleType"] == "tvEpisode"].copy()
    episodes = episodes.merge(episode, on="tconst", how="inner")
    episodes = episodes.merge(ratings, on="tconst", how="inner")

    episodes["numVotes"] = pd.to_numeric(episodes["numVotes"], errors="coerce")
    episodes = episodes[episodes["numVotes"] >= MIN_VOTES]

    series_ids = episodes["parentTconst"].unique().tolist()
    series_info = basics[basics["tconst"].isin(series_ids)][
        ["tconst", "primaryTitle", "runtimeMinutes"]
    ].rename(columns={"tconst": "parentTconst", "primaryTitle": "seriesTitle"})

    all_eps_for_series = basics[basics["titleType"] == "tvEpisode"].merge(
        episode, on="tconst", how="inner"
    )
    all_eps_for_series = all_eps_for_series[
        all_eps_for_series["parentTconst"].isin(series_ids)
    ][["tconst", "parentTconst", "seasonNumber", "episodeNumber", "runtimeMinutes"]]

    all_eps_for_series["runtimeMinutes"] = pd.to_numeric(
        all_eps_for_series["runtimeMinutes"], errors="coerce"
    ).fillna(0)
    all_eps_for_series["seasonNumber"] = pd.to_numeric(
        all_eps_for_series["seasonNumber"], errors="coerce"
    )
    all_eps_for_series["episodeNumber"] = pd.to_numeric(
        all_eps_for_series["episodeNumber"], errors="coerce"
    )

    total_binge = (
        all_eps_for_series.groupby("parentTconst")["runtimeMinutes"].sum().to_dict()
    )

    all_eps_sorted = all_eps_for_series.sort_values(
        ["parentTconst", "seasonNumber", "episodeNumber"]
    )
    all_eps_sorted["cum_runtime"] = all_eps_sorted.groupby("parentTconst")[
        "runtimeMinutes"
    ].cumsum()
    watch_to_here_map = dict(
        zip(all_eps_sorted["tconst"], all_eps_sorted["cum_runtime"])
    )

    episodes = episodes.merge(series_info, on="parentTconst", how="left")
    episodes["averageRating"] = pd.to_numeric(episodes["averageRating"], errors="coerce")
    episodes = episodes.sort_values(
        ["averageRating", "numVotes"], ascending=[False, False]
    ).head(TOP_N)

    records = []
    for _, row in episodes.iterrows():
        tconst = row["tconst"]
        parent = row["parentTconst"]
        year = row.get("startYear")
        year = int(year) if pd.notna(year) else None
        runtime_min = row.get("runtimeMinutes")
        runtime_seconds = (
            int(float(runtime_min) * 60) if pd.notna(runtime_min) else None
        )
        season_num = row.get("seasonNumber")
        ep_num = row.get("episodeNumber")

        records.append(
            {
                "episode_id": tconst,
                "episode_title": row.get("primaryTitle"),
                "year": year,
                "runtime_seconds": runtime_seconds,
                "rating": float(row["averageRating"]),
                "votes": int(row["numVotes"]),
                "series_id": parent,
                "series_title": row.get("seriesTitle"),
                "season_number": int(season_num) if pd.notna(season_num) else None,
                "episode_number": int(ep_num) if pd.notna(ep_num) else None,
                "total_binge_seconds": float(total_binge.get(parent, 0) * 60),
                "watch_to_here_seconds": float(watch_to_here_map.get(tconst, 0) * 60),
                "imdb_url": f"https://www.imdb.com/title/{tconst}/",
                "series_imdb_url": f"https://www.imdb.com/title/{parent}/",
            }
        )

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "min_votes": MIN_VOTES,
        "count": len(records),
        "episodes": records,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(records)} episodes to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
