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

### Options

| Flag | Long                           | Description                                                                                                    |
| ---- | ------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `-l` | `--languages`                  | Comma-separated audio & subtitle languages to keep (ISO 639 codes). Required.                                  |
| `-s` | `--sub-languages`              | Comma-separated subtitle-specific languages. Overrides `--languages` for subtitles.                            |
| `-r` | `--recurse`                    | Recurse into directories.                                                                                      |
| `-d` | `--dry-run`                    | Preview changes without modifying files.                                                                       |
| `-v` | `--verbose`                    | Increase verbosity. Use `-vv` for maximum detail.                                                              |
| `-q` | `--quiet`                      | Suppress all output.                                                                                           |
| `-u` | `--und-language`               | Relabel `und` (undetermined) tracks to the given language code during remux.                                   |
| `-U` | `--strip-und-language`         | Strip `und` tracks instead of keeping them. By default, `und` tracks are kept.                                 |
| `-S` | `--no-subtitles`               | Strip all subtitles when none match the specified languages. By default, all subtitles are kept if none match. |
| `-T` | `--no-title`                   | Do not rewrite the MKV metadata title with the filename stem.                                                  |
| `-L` | `--no-symlinks`                | Do not follow symlinks.                                                                                        |
| `-i` | `--ignore`                     | Comma-separated list of glob patterns to ignore.                                                               |
| `-t` | `--timestamps`                 | Track file modification times to skip unchanged files on subsequent runs.                                      |
| `-C` | `--timestamps-no-check-config` | Skip config comparison when loading timestamps.                                                                |
| `-A` | `--after`                      | Only process files modified after this timestamp (epoch or datetime string).                                   |
| `-b` | `--mkvmerge-bin`               | Path to the `mkvmerge` binary.                                                                                 |
| `-c` | `--config`                     | Path to an alternate YAML config file.                                                                         |
| `-m` | `--media-type`                 | Media type hint: `movie` or `tv`. Improves online lookup accuracy.                                             |
|      | `--tmdb-api-key`               | TMDB API key for online language lookup.                                                                       |
|      | `--tvdb-api-key`               | TVDB API key for TV series language lookup.                                                                    |
|      | `--cache-expiry-days`          | Days before no-result cache entries expire and are re-queried. Default: 30.                                    |
| `-V` | `--version`                    | Show version and exit.                                                                                         |

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
  Breaking Bad/
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

- `{tmdb-550}` — TMDB ID
- `{imdb-tt0137523}` — IMDB ID (looked up via TMDB)
- `{tvdb-81189}` — TVDB ID

Example: `Breaking Bad {tvdb-81189} S01E01.mkv`

### Caching

Lookup results are cached in `~/.config/nudebomb/cache/` to avoid redundant API
calls. Cache entries with a found language never expire. Entries where no
language was found expire after `--cache-expiry-days` (default: 30) and are
re-queried.

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
