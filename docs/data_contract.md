# Data contract: what we use from TMDb

Snapshot of 20 Nov 2026. Source: `GET /movie/{id}` (details) and `GET /movie/{id}/credits` (credits). TMDb's data is maintained by volunteers and comes with no warranty (TMDB API Terms of Use (last updated 20 October 2023), section 6, Disclaimer of Any Warranty; verified).

## Details

| Field | Our column | Type | Meaning | How "missing" appears | What we do |
|---|---|---|---|---|---|
| `id` | `tmdb_id` | integer | TMDb film id | never | key; must equal the requested id (C-07) |
| `imdb_id` | `imdb_id` | text | IMDb id | null or "" | used for the IMDb cross-check (I-01) |
| `title`, `original_title` | same | text | titles | "" | reference only |
| `release_date` | `release_date_raw`, `release_date`, `release_year` | text, date | first release date | "" | raw kept; parsed as date; window assignment |
| `status` | `status` | text | e.g. Released, Rumored | — | non-released films excluded from money measures (S20) |
| `budget` | `budget` | whole number | production budget, assumed US dollars (S21) | 0 | 0 treated as not reported (S04) |
| `revenue` | `revenue` | whole number | box-office revenue, assumed US dollars | 0 | 0 treated as not reported (S03) |
| `vote_count` | `vote_count` | whole number | TMDb users who rated the film | 0 | second measure (D7) |
| `vote_average` | `vote_average` | decimal | average rating | 0 | reference |
| `popularity` | `popularity` | decimal | TMDb's own interest score, changes daily | — | reference only |
| `belongs_to_collection.id`, `.name` | `collection_id`, `collection_name`, `is_franchise` | integer, text | the series the film belongs to | null | null = standalone (ADR-012) |
| `genres[].name` | `n_genres`, `primary_genre`, `genres_all` | count, text | genres in TMDb's order | [] | ADR-011 |
| `production_companies` | `n_production_companies` | count | | [] | reference |
| `adult`, `video` | same | true/false | adult flag; direct-to-video flag | — | checked in the cleaning stage |
| `runtime` | `runtime` | whole number | minutes | 0 or null | reference |

## Credits

| Field | Our column | Meaning | What we do |
|---|---|---|---|
| `cast[].id`, `.name`, `.order` | `person_id`, `name`, `cast_order`, `billing_rank` | billed cast | three lowest `order` = lead actors (ADR-014) |
| `crew[].id`, `.name`, `.job` | `person_id`, `name` | crew | `job == "Director"` = director (ADR-014) |

## Rules that apply to this data

- Saved responses expire after 180 days (TMDb terms, 1.C; ADR-008).
- Saved responses and outputs are not committed or shared (TMDb terms, 1.C; ADR-004).
- The flatten stage reads the two snapshot files `data/raw/snapshot_movie.jsonl` and `data/raw/snapshot_credits.jsonl`, built from the per-film files and rebuilt when they no longer match the fetch log (ADR-030); they are a second copy of the same data, with the same 180-day rule and the same limits on sharing.
- Any product built on it shows TMDb's notice (README).
- Reading `films.csv` back: blanks in text columns become missing, except `release_date_raw`, which stays text. Use `read_films()` rather than a plain read.
