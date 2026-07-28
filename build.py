#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "requests>=2.31.0",
#     "pandas>=2.0.0",
#     "Pillow>=10.0.0",
# ]
# ///

"""
Local Build Script for TopEpisode.com
Replicates the data fetching and chunking logic of the GitHub Actions workflow,
and compresses the output chunks. Uses `uv` to automatically manage dependencies.
"""

import os
import subprocess
import gzip
import shutil
import glob
import sys

def main():
    print("=== Checking Environment ===")
    os.environ["MIN_VOTES"] = "100"
    os.environ["TOP_N"] = "100000"
    
    print("\n=== Fetching Data ===")
    print(f"Running scraper with MIN_VOTES={os.environ['MIN_VOTES']} and TOP_N={os.environ['TOP_N']}")
    # Run the scraper using the current python executable (which uv has prepared with dependencies)
    try:
        subprocess.run([sys.executable, "scraper/fetch_top_episodes.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: scraper failed with exit code {e.returncode}")
        sys.exit(1)
        
    print("\n=== Processing Chunks ===")
    os.makedirs("site", exist_ok=True)
    chunks = glob.glob("data/top_episodes_*.csv")
    
    if not chunks:
        print("Warning: No chunk files found in data/")
    
    for f in chunks:
        base = os.path.basename(f)
        out_path = os.path.join("site", f"{base}.gz")
        print(f"Compressing {base}...")
        with open(f, 'rb') as f_in:
            with gzip.open(out_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

    print("\n=== Generating OG Image ===")
    try:
        subprocess.run([sys.executable, "generate_og_image.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Warning: OG image generation failed (exit code {e.returncode}), continuing...")
                
    print("\n=== Done ===")
    print("Data successfully built. You can test the site locally by running:")
    print("python3 -m http.server --directory site 8000")

if __name__ == "__main__":
    main()
