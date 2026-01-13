# YouTube parquet filtering (`youtube_cleanning.py`)

This script reads a country-specific YouTube parquet file from GCS, enriches it with candidate metadata from a YAML config, and produces:

1) A **filtered parquet** (only “relevant” videos) written back to GCS  
2) A **non-relevant CSV** (videos that don’t mention any candidate name variation) written locally  
3) A **relevance summary CSV** (counts by candidate_id) written locally

The goal is to keep only videos whose **title or description contains at least one candidate `name_variation`**, and optionally meets a **views threshold**.

---

## Inputs

### 1) Source parquet (GCS)

The script reads exactly one parquet file based on `--country` and `--prefix`:

```
gs://<bucket>/<prefix>/yt_keywordpost_<country>.parquet
```

Examples:

- Honduras:
  ```
  gs://trust-prd/stg/keywordpost/youtube/yt_keywordpost_honduras.parquet
  ```
- Bolivia:
  ```
  gs://trust-prd/stg/keywordpost/youtube/yt_keywordpost_bolivia.parquet
  ```

### 2) YAML config (local)

The script loads the country YAML from:

```
config/<country>.yaml
```

It expects:

- `candidates:` to be a **list**
- each candidate to have `candidate_id`, `name`, and `name_variations`

Example:

```yaml
candidates:
  - candidate_id: bol19dori
    name: Samuel Doria Medina
    name_variations:
      - Doria Medina
```

---

## What “relevant” means

For each video row, the script checks whether **any candidate name variation appears** in the video’s:

- `title`
- `description`

This is an **exact substring match** (case-insensitive after normalization).

### Buckets

The script separates videos into 3 mutually exclusive buckets:

1) **Relevant (strong)**  
   Has at least one `name_variation` match in title/description **and** `view_count >= threshold` (currently `100`).  
   These rows become `relevant_videos_count` and are what get written to the filtered parquet.

2) **Relevant (few views)**  
   Has at least one `name_variation` match, but `view_count < threshold`.  
   These rows count as `relevant_few_views_count`.

3) **Non-relevant**  
   No `name_variation` matches at all in title/description.  
   These rows count as `non_relevant_videos_count` and get written to the non-relevant CSV.

---

## Outputs

### 1) Filtered parquet (written to GCS)

This parquet contains **only “Relevant (strong)” rows**, i.e., the ones counted as `relevant_videos_count`.

Path pattern:

```
gs://<bucket>/stg/keywordpost_filtered/youtube/yt_keywordpost_ft_<country>.parquet
```

Examples:

- Honduras:
  ```
  gs://trust-prd/stg/keywordpost_filtered/youtube/yt_keywordpost_ft_honduras.parquet
  ```
- Bolivia:
  ```
  gs://trust-prd/stg/keywordpost_filtered/youtube/yt_keywordpost_ft_bolivia.parquet
  ```

### 2) Non-relevant CSV (local)

Saved locally as:

```
./out/yt_keywordpost_<country>_non_relevant.csv
```

Contains only rows where **no candidate variation matched**.

### 3) Relevance summary CSV (local)

Saved locally as:

```
./out/yt_keywordpost_<country>_relevance_summary.csv
```

This summary aggregates counts by `candidate_id`.

---

## Summary columns

The relevance summary includes:

- `candidate_id`  
  Candidate identifier from the parquet / YAML.

- `candidate_name`  
  Candidate name from YAML after enrichment.

- `video_ids_count`  
  Total number of videos in the parquet for this candidate_id.

- `relevant_videos_count`  
  Videos that match a name variation **and** have `view_count >= threshold`.  
  These are the rows saved to the filtered parquet.

- `relevant_few_views_count`  
  Videos that match a name variation but have `view_count < threshold`.

- `non_relevant_videos_count`  
  Videos that have **no** name variation match.

- `relevant_pct`  
  `relevant_videos_count / video_ids_count`.

---

## How to run

### Honduras

```bash
python src/data_analysis/youtube_cleanning.py   --bucket trust-prd   --prefix stg/keywordpost/youtube   --country honduras
```

### Bolivia

```bash
python src/data_analysis/youtube_cleanning.py   --bucket trust-prd   --prefix stg/keywordpost/youtube   --country bolivia
```

Optional (if you want to force a GCP project):

```bash
  --project YOUR_GCP_PROJECT_ID
```
