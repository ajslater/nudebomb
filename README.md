# Nudebomb

The Nudebomb recursively strips matroska media files of unwanted audio and
subtitle tracks.

## News

You may find user focused nudebomb changes in the
[NEWS file](https://github.com/ajslater/nudebomb/tree/NEWS.md).

## Requirements

- MKVToolNix
- Python3

## Install

    pip install

## Usage

### Posix

    nudebomb -rl eng,fre /mnt/movies

### Windows

    nudebomb -b C:\\Program/ Files\MKVToolNix\mkvmerge.exe -rl eng,jap \\nas\movies

## Config

You may configure Nudebomb options via the command, a yaml config file and
environment variables.

### Environment variable format

Prefix environment variables with `NUDEBOMB_NUDEBOMB__` and enumerate lists
elements:

```sh
NUDEBOMB_NUDEBOMB__RECURSE=True
NUDEBOMB_NUDEBOMB__LANGUAGES__0=und
NUDEBOMB_NUDEBOMB__LANGUAGES__1=eng
```

## Lang Files

While you may have a primary language, you probably want videos from other
countries to keep their native language as well. Lang files let you do this.

Lang files are persistent files on disk that nudebomb parses to keep to all
languages in them in the mkvs in the current directory and all mkvs in sub
directories.

Valid lang file names are: 'lang', 'langs', '.lang', or '.langs' They include
comma separated list of languages to keep like the `-l` option.

e.g. You may have an entire collecttion of different TV shows with a root lang
file containing the `eng` language. Under that directory you may have a specific
TV show directory with lang file containing `jpn`. All mkvs in season
directories under that would then keep both the `eng` and `jpn` languages, while
other TV shows would keep only `eng` languages.

For each mkv file, nudebomb looks up the directory tree for each parent lang
file and uses the union of all languages found to determine what languages to
keep.

### APIs

Langfiles would be obsolete if nudebomb could deterimining native languages for
mkv files by polling and caching results from major online media databases. It's
the right thing to do, but I don't care to implement it. Patches or forks
welcome.

## Inspiration

Nudebomb is a radical fork of [mkvstrip](https://github.com/willforde/mkvstrip).
It adds recursion, lang files, timestamps and more configuration to mkvstrip and
fixes some minor bugs.
