# Absolute Cinema TV Episodes

> Top episodes of TV according to IMDb — sortable, filterable, self-updating.

Inspired by the IMDb search feature at
https://www.imdb.com/search/title/?title_type=tv_episode&num_votes=1000,&sort=user_rating,desc

## How it works

1. **`scraper/fetch_top_episodes.py`** fetches the data and partitions it across multiple axes (Score and Votes) into 6 distinct, non-overlapping `.csv` chunk files. (It defaults to attempting an undocumented IMDb GraphQL API for up-to-date binge metrics, and automatically falls back to IMDb's official non-commercial dataset dumps).
2. **`.github/workflows/update-and-deploy.yml`** runs daily, generates the data fresh, uses `gzip -c` to highly compress the CSV chunks into `site/`, and deploys to GitHub Pages.
3. **`site/index.html`** is a static page (using PapaParse and fflate via CDN) with a sortable/filterable, virtually-scrolled table. It features **Matrix Lazy Loading**, downloading only the absolute top episodes initially, and asynchronously fetching and merging the remaining chunks in the background as the user relaxes the filter sliders!

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
./build.py
```

This self-contained Python script uses [`uv`](https://github.com/astral-sh/uv) to automatically manage dependencies! It will effortlessly spin up a virtual environment, install requirements, run the scraper to generate the partitioned dataset, gzip the chunks into `site/`, and provide you with a command to test the live frontend locally!

## Enabling GitHub Pages

In the repo settings, under **Pages**, set the source to
**GitHub Actions**. The included workflow will handle the rest.

## Config

Environment variables read by the scraper (also editable in the workflow
file):

| Variable      | Default                  | Meaning                              |
|---------------|---------------------------|---------------------------------------|
| `MIN_VOTES`   | `100`                     | Minimum IMDb vote count to qualify    |
| `TOP_N`       | `40000`                   | How many top episodes to keep         |
| `OUTPUT_PATH` | `data/top_episodes.csv`  | Base path for resulting CSV chunks     |

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by IMDb.com,
Inc. or its affiliates. Data is used under IMDb's non-commercial dataset
terms for personal/non-commercial use.
