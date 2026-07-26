# Absolute Cinema TV Episodes

> Top episodes of TV according to IMDb — sortable, filterable, self-updating.

Inspired by the IMDb search feature at
https://www.imdb.com/search/title/?title_type=tv_episode&num_votes=1000,&sort=user_rating,desc

## How it works

1. **`scraper/fetch_top_episodes.py`** downloads IMDb's official, free,
   non-commercial daily dataset dumps (`title.basics`, `title.ratings`,
   `title.episode`) from `datasets.imdbws.com`, filters TV episodes by a
   minimum vote count, sorts by rating, and computes for each episode:
   - `total_binge_seconds`: total runtime of every episode in the parent
     series (how long it takes to watch the whole show).
   - `watch_to_here_seconds`: cumulative runtime from S01E01 through the
     episode in question.
2. The script writes `data/top_episodes.json`, which is copied into
   `site/top_episodes.json` for the static frontend to fetch.
3. **`site/index.html`** is a static, dependency-free page with a
   sortable/filterable table (rating, votes, season/episode, watch-to-here
   hours, total binge hours, poster thumbnail, links to IMDb).
4. **`.github/workflows/update-and-deploy.yml`** runs on a daily schedule
   (and on every push), regenerates the data, commits it back to the repo,
   and deploys `site/` to GitHub Pages. No server, no CORS proxy, no paid
   API — everything runs on GitHub's free infrastructure.

## Why datasets instead of scraping the search page

IMDb's official GraphQL/API access via AWS Data Exchange is a paid,
five/six-figure-per-year commercial product — not viable for a hobby
project. IMDb does, however, publish free
[non-commercial dataset dumps](https://developer.imdb.com/non-commercial-datasets/)
updated daily, containing ratings, vote counts, titles, runtimes and
episode-parent relationships for every title on the platform. That's
enough to fully reconstruct (and enrich, with binge-time metrics) the
`num_votes` + `sort=user_rating,desc` search view without ever touching
IMDb's website — no scraping, no fragile HTML parsing, no rate-limit risk.

## Setup / local run

```bash
pip install -r requirements.txt
MIN_VOTES=1000 TOP_N=250 python scraper/fetch_top_episodes.py
cp data/top_episodes.json site/top_episodes.json
python -m http.server --directory site 8000
# open http://localhost:8000
```

## Enabling GitHub Pages

In the repo settings, under **Pages**, set the source to
**GitHub Actions**. The included workflow will handle the rest.

## Config

Environment variables read by the scraper (also editable in the workflow
file):

| Variable      | Default                  | Meaning                              |
|---------------|---------------------------|---------------------------------------|
| `MIN_VOTES`   | `1000`                    | Minimum IMDb vote count to qualify    |
| `TOP_N`       | `250`                     | How many top episodes to keep         |
| `OUTPUT_PATH` | `data/top_episodes.json`  | Where to write the resulting JSON     |

## Naming

`abs-tv.com` was one idea (Absolute [Cinema] TV). Other options considered:
`EpisodePeak`, `RatedEp`, `BingeBoard`, `TopEp.tv`, `PeakEpisode`.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by IMDb.com,
Inc. or its affiliates. Data is used under IMDb's non-commercial dataset
terms for personal/non-commercial use.
