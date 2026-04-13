# Nudebomb

Nudebomb recursively strips MKV (Matroska) files of unwanted audio and subtitle
tracks, keeping only the languages you specify.

## Installation

### Requirements

- [MKVToolNix](https://mkvtoolnix.download/) — provides the `mkvmerge` binary.
  Available via Homebrew, apt, or your favorite package manager.

### Install

```sh
pip install nudebomb
```

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install nudebomb
```

## Quick Start

Strip all non-English tracks from a directory tree:

```sh
nudebomb -rl eng /mnt/movies
```

Keep English and French, recurse, and use timestamps to skip already-processed
files:

```sh
nudebomb -rtl eng,fra /mnt/movies
```

Dry run on a single file to preview what would be stripped:

```sh
nudebomb -dvvl eng movie.mkv
```

```text
Stripping languages except eng, und.
Searching for MKV files to process:
Checking movie.mkv
    audio: 1 eng
    audio: 2 eng
    audio: 3 eng
    subtitles: 4 eng
    subtitles: 5 eng
    Already stripped movie.mkv
done.
```

## Usage

```text
nudebomb [options] path [path ...]
```

Paths can be individual MKV files or directories. Use `-r` to recurse into
directories.

## Configuration

Nudebomb is configured through three layers, each overriding the previous:

1. **YAML config file** — `~/.config/nudebomb/config.yaml`
2. **Environment variables**
3. **Command-line arguments**

### Config File

```yaml
nudebomb:
    languages:
        - eng
        - und
    recurse: true
    timestamps: true
    media_type: movie
    tmdb_api_key: your-api-key-here
    tvdb_api_key: your-api-key-here
```

All command-line options have config file equivalents. Use `-c` to specify an
alternate config file path.

### Environment Variables

Prefix with `NUDEBOMB_NUDEBOMB__`. List items are enumerated:

```sh
export NUDEBOMB_NUDEBOMB__RECURSE=True
export NUDEBOMB_NUDEBOMB__LANGUAGES__0=eng
export NUDEBOMB_NUDEBOMB__LANGUAGES__1=fra
export NUDEBOMB_NUDEBOMB__TMDB_API_KEY=your-api-key-here
```

## Lang Files

Lang files let you specify additional languages to keep on a per-directory
basis. This is useful when your collection spans multiple languages — you want
most content to keep English, but a specific show to also keep Japanese.

### How They Work

Place a file named `lang`, `langs`, `.lang`, or `.langs` in any directory. The
file contains a comma-separated list of ISO 639 language codes:

```text
jpn
```

Nudebomb walks up the directory tree from each MKV file, collecting languages
from every lang file it finds. The final set of languages to keep is the union
of `--languages`, all lang file languages from the current directory up to the
top-level path, and any online lookup results.

### Example

```text
/mnt/tv/
  .lang          # contains: eng
  GI Robot/
    Season 1/
      episode.mkv    # keeps: eng, und
  Anime Show/
    .lang            # contains: jpn
    Season 1/
      episode.mkv    # keeps: eng, jpn, und
```

## Online Language Lookup

When no lang files contribute additional languages for a file, nudebomb can look
up the original language of the media from online databases and add it to the
languages to keep. This requires an API key.

### TMDB (The Movie Database)

Works for both movies and TV series. Get an API key at
[themoviedb.org](https://www.themoviedb.org/settings/api).

```sh
nudebomb -rl eng --tmdb-api-key YOUR_KEY --media-type movie /mnt/movies
```

### TVDB (TheTVDB)

Specialized for TV series. Get an API key at
[thetvdb.com](https://thetvdb.com/dashboard/account/apikeys). When both keys are
configured and `--media-type tv` is set, TVDB is tried first for TV content.

```sh
nudebomb -rl eng --tvdb-api-key YOUR_KEY --media-type tv /mnt/tv
```

### Filename Parsing

Nudebomb parses media filenames to extract titles, years, and database IDs. For
best results, use standard naming conventions:

- **Movies**: `Movie Title (2024).mkv` or `Movie.Title.2024.BluRay.mkv`
- **TV**: `Show Name S01E02.mkv` or `Show.Name.1x02.mkv`

You can embed database IDs in curly braces for exact matching:

- `{tmdb-696}` — TMDB ID
- `{imdb-tt022345}` — IMDB ID (looked up via TMDB)
- `{tvdb-5780}` — TVDB ID

Example: `{tvdb-1234} S01E01.mkv`

### Caching

Lookup results are cached in `~/.cache/nudebomb/` to avoid redundant API calls.
Cache entries with a found language never expire. Entries where no language was
found expire after `--cache-expiry-days` (default: 30) and are re-queried.

## Dot Color Key

When running at default verbosity, nudebomb prints single characters to indicate
progress:

| Char        | Meaning                                               |
| ----------- | ----------------------------------------------------- |
| `.`         | MKV skipped (ignored, already stripped, or cache hit) |
| `.` (green) | Skipped because timestamp unchanged                   |
| `O`         | Online lookup succeeded                               |
| `x`         | Online lookup returned no result                      |
| `X`         | Online lookup error or rate limited                   |

Use `-vv` for full text descriptions instead of dots.

## Development

Source code is hosted at [GitHub](https://github.com/ajslater/nudebomb).

## Inspiration

Nudebomb is a radical fork of [mkvstrip](https://github.com/willforde/mkvstrip).
It adds recursion, lang files, timestamps, online language lookup, and more
configuration options.
