# 📰 Nudebomb News

## v1.8.1

### ✨ Added

- Supports Python 3.15 and requires python-dateutil 3.0.

## v1.8.0

### ✨ Added

- `nudebomb doctor` checks mkvmerge, the TMDB and TVDB API keys, and the lookup
  cache directory, and reports what the next run would make of the timestamps
  files under any paths given. It takes the same options as a run, writes
  nothing, and exits 1 if a check fails. `-q` prints only problems.

### 🐛 Fixed

- A rejected TVDB API key or unreachable TVDB no longer crashes the run. TVDB
  lookups are skipped with one error and the run continues. Runs that don't need
  TVDB, like movie runs, no longer contact it.

### 🧑‍💻 Developer

- Requires treestamps 5.2.0.

## v1.7.0

### 💥 Breaking Changes

- Requires Python 3.11 and treestamps 5.1.1.

## v1.6.2

### 🧑‍💻 Developer

- Update confuse dependency

## v1.6.1

### 🐛 Fixed

- Warnings from the timestamps library, like the one for discarding timestamps
  after a `.nudebomb.yaml` change, print in warning yellow with the rest of the
  output instead of as uncolored text on stderr.
- A timestamps file discarded for a config mismatch is now rewritten by the run
  that discards it, even when that run changes no files. Previously the rejected
  file survived unchanged and warned about the same mismatch on every subsequent
  run. Requires treestamps 5.0.1.

## v1.6.0

### ✨ Added

- Timestamps survive upgrades that record new options. Only a changed option
  value invalidates them, so stamp files written before an option joined the
  recorded set stay valid at its default.
- Timestamp files now open with a comment explaining what they are, that they
  are machine-written, and that deleting one just re-examines that tree.
- `media_type` is recorded, so switching between movie and tv lookups
  re-examines the tree instead of reusing the other type's results.
- Discarding timestamps because a `.nudebomb.yaml` changed now says so, instead
  of naming an internal key.

### ♻️ Changed

- Timestamp files no longer record run-scoped options or API keys; only the
  options that decide which files and tracks are affected.
- Trees holding `.nudebomb.yaml` files are re-examined once after upgrading,
  because the directory config fingerprint changed.

### 🐛 Fixed

- Config files are written atomically. A crash or full disk during `-w`, `-W`,
  or the automatic langfile migration can no longer truncate a hand-written
  config.
- Comment and formatting edits to a `.nudebomb.yaml` no longer re-examine its
  tree on timestamped runs; only option value edits do.
- `ignore` globs are recorded again, so changing them re-examines the tree.

### 🧑‍💻 Developer

- Requires treestamps 5.0.0.

## v1.5.0

### 💥 Breaking Changes

- `-c`/`--config` now fully replaces your user config for the run instead of
  layering on top of it (packaged defaults still apply beneath).

### ✨ Added

- Per-directory `.nudebomb.yaml` config files override settings for a subtree.
- Deprecated `.lang` files are auto-migrated to `.nudebomb.yaml` and removed.
- `-w`/`--write-config` saves the invoked options to your user config.
- `-W`/`--write-dir-config` saves them into each target directory.
- `--write-config-file PATH` writes the config to a specific file.

### ♻️ Changed

- Per-file checks run once during the walk, and the file-counting pass is
  skipped in quiet mode or without a TTY.

### 🐛 Fixed

- Online lookups no longer fail on standard `Title (Year)` filenames.
- One unreadable or corrupt MKV no longer aborts the whole run.
- Nudebomb exits nonzero when any file errors, so scripts and cron can detect
  it.
- Stalled network lookups now time out instead of freezing the run.
- Release tags like `[x265]` in filenames no longer break the progress display
  or the end-of-run summary.
- Shows with non-Latin titles now match via their aliases and translations.
- `--after` no longer crashes on every use.
- Language codes match more reliably: 2-letter codes are normalized to match
  tracks, and `-l "eng, fra"` tolerates spaces.
- API keys are redacted from logs and the summary.
- Corrupt lookup-cache entries self-heal instead of crashing, and stale wrong
  matches expire after a year.
- Windows finds the default mkvmerge via `%ProgramFiles%`.
- Passing a directory without `-r` now warns instead of silently doing nothing.
- Per-directory `media_type` and `timestamps` settings now take effect.

## v1.4.0

### ♻️ Changed

- Use rich\_argparse to format help.

## v1.3.1

### 🐛 Fixed

- Expose action logging that was hidden.
- Expose mkvmerge live progress that got hidden.

## v1.3.0

### 🧑‍💻 Developer

- Update to confuse 2.2.0
- Introduce NudebombSettings class to type the config.

## v1.2.1

### 🐛 Fixed

- Fix mkvmerge output being squished into one line.

## v1.2.0

### ♻️ Changed

- New Progress and logging output

### 🐛 Fixed

- Fix "Already Stripped" state not writing timestamps.

## v1.1.0

### ♻️ Changed

- Parallelize online database lookups.

## v1.0.4

### ♻️ Changed

- Cache id lookups as well as title & year lookups.

## v1.0.3

### 🐛 Fixed

- More fixes for title parsing.

## v1.0.2

### 🐛 Fixed

- Fix title parsing for online lookup.

## v1.0.1

### 🐛 Fixed

- Fix crash creating cache.

## v1.0.0

### ✨ Added

- Fetch media file language from tmdb and tvdb. You don't have to use lang files
  if your media is in an online database.
- Relabel und tracks with a preferred language option.

### ♻️ Changed

- Don't write timestamps if nothing stripped.

## v0.4.9

### 🧑‍💻 Developer

- Update pycountry

## v0.4.8

### ✨ Added

- Add type hints and py.typed sentinel file.

## v0.4.7

### ✨ Added

- Support for Python 3.14

## v0.4.6

### ♻️ Changed

- The confuse library dependency doesn't support Python 3.14. So neither does
  nudebomb :(

## v0.4.5

### 🐛 Fixed

- fix cli verbosity counting

## v0.4.4

### ♻️ Changed

- new treestamps printer flushes more and has more consistent colors

## v0.4.3

### 🐛 Fixed

- fix minor printing errors

## v0.4.2

### 🐛 Fixed

- fix colors

## v0.4.1

### ♻️ Changed

- updated colors

## v0.4.0

### 💥 Breaking Changes

- updated treestamps - all timestamps will miss on first run

### ✨ Added

- verbose option can be called multiple times
- quiet option

### ♻️ Changed

- changed colors

### 🧑‍💻 Developer

- uv build system

## v0.3.10

### ♻️ Changed

- Remove latency from progress output.

## v0.3.9

### 🐛 Fixed

- Resolve all top paths first thing. Fixes bad symlink behavior.

## v0.3.8

### 🐛 Fixed

- Fix crash with unresolved path and timestamps

## v0.3.7

### ✨ Added

- Add a dot color key to help.

## v0.3.6

### 🐛 Fixed

- Fix treestamps wal file bug with illegal characters in filename.

## v0.3.5

### 💥 Breaking Changes

- Require python 3.10

## v0.3.4

### 🧑‍💻 Developer

- Update deps.

## v0.3.3

### 🐛 Fixed

- Upstream treestamps fixes bugs.

## v0.3.2

### ♻️ Changed

- Upstream treestamps returns to relative stamp paths for portability.

## v0.3.1

### 🐛 Fixed

- Upstream treestamps fixes crashes and check\_config option.

## v0.3.0

### ✨ Added

- New ignore timestamps for one run but write them option.

### 🧑‍💻 Developer

- Update deps including new treestamps.

## v0.2.6

### 🧑‍💻 Developer

- Update uv.lockfile & dev deps

## v0.2.5

### 🧑‍💻 Developer

- Update confuse library to latest version

## v0.2.4

### ✨ Added

- Progress dots in non-verbose mode.

## v0.2.3

### 💥 Breaking Changes

- Renamed subs\_languages config option to sub\_languages.

### ✨ Added

- More output about what nudebomb is doing.

### 🐛 Fixed

- Searching for langfiles obeys symlinks preference.

## v0.2.2

### 🐛 Fixed

- Fix timestamps factory breaking.

## v0.2.1

### 🐛 Fixed

- Timestamps respect symlinks option

## v0.2.0

### ✨ Added

- Ignore option

## v0.1.3

### 🐛 Fixed

- Fix timestamps not recording sometimes.

## v0.1.2

### 🐛 Fixed

- Timestamps more resilient to errors.

## v0.1.1

### 🐛 Fixed

- Fix treestamps type issue.
- Timestamps do not set on dry run.

## v0.1.0

### ✨ Added

- First Release
