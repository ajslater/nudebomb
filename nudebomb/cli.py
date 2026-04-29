"""Command line interface for nudebomb."""

from argparse import Action, ArgumentParser, Namespace, RawDescriptionHelpFormatter
from collections.abc import Sequence
from typing import Any, Final

from rich.console import Console
from typing_extensions import override

from nudebomb.config import NudebombConfig
from nudebomb.log import setup as setup_logging
from nudebomb.log.styles import MARKS
from nudebomb.version import VERSION
from nudebomb.walk import Walk


class CommaListAction(Action):
    """Split arguments by commas into a list."""

    DELINEATOR: str = ","

    @override
    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Split by delineator and assign to dest variable."""
        if isinstance(values, str):
            values = values.strip().split(self.DELINEATOR)
        setattr(namespace, self.dest, values)


# Order + label for each mark in the help epilogue legend. The char and
# style are pulled from the centralized MARKS table so the legend can
# never drift from what the bar actually renders.
CHAR_KEY_LABELS: Final[tuple[tuple[str, str], ...]] = (
    ("ignored", "MKV ignored/skipped"),
    ("skipped_timestamp", "MKV skipped (timestamp unchanged)"),
    ("already_stripped", "MKV already stripped"),
    ("stripped", "MKV stripped tracks"),
    ("dry_run", "MKV not remuxed (dry run)"),
    ("warning", "Warning"),
    ("error", "Error"),
    ("lookup_hit", "Remote DB lookup succeeded"),
    ("lookup_no_result", "Remote DB lookup no result"),
    ("lookup_rate_limited", "Remote DB rate limited"),
    ("lookup_error", "Remote DB error"),
)


def get_progress_char_key() -> str:
    """Create the progress char legend for the help epilogue."""
    console = Console(record=True, force_terminal=True, no_color=False)
    console.begin_capture()
    console.print("[bold]Progress char key:[/bold]")
    for kind, label in CHAR_KEY_LABELS:
        mark = MARKS[kind]
        console.print(f"\t[{mark.style}]{mark.char}[/{mark.style}]  {label}")
    return console.end_capture()


def get_arguments(
    params: tuple[str, ...] | None = None,
) -> Namespace:
    """Command line interface."""
    description = "Strips unnecessary tracks from MKV files."
    epilog = get_progress_char_key()
    parser = ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Enable mkvmerge dry run for testing.",
    )
    parser.add_argument(
        "-b",
        "--mkvmerge-bin",
        action="store",
        help="The path to the MKVMerge executable.",
    )
    parser.add_argument(
        "-l",
        "--languages",
        action=CommaListAction,
        help=(
            "Comma-separated list of audio and subtitle languages to retain. "
            "e.g. eng,fra."
        ),
    )
    parser.add_argument(
        "-m",
        "--media-type",
        action="store",
        default="",
        help="TMBD media type. Specify 'movie' or 'tv' type to target tmbd lookups.",
    )
    parser.add_argument(
        "-u",
        "--und-language",
        action="store",
        help=(
            "Relabel 'und' undetermined or untagged language tracks to the "
            "specified ISO 639 language code during remux. e.g. 'eng' or 'en'."
        ),
    )
    parser.add_argument(
        "-U",
        "--strip-und-language",
        action="store_true",
        help=(
            "Strip the 'und' undetermined or untagged language tracks. "
            "By default nudebomb does not strip these tracks."
        ),
    )
    parser.add_argument(
        "-s",
        "--sub-languages",
        action=CommaListAction,
        required=False,
        help=(
            "Comma-separated list of subtitle specific languages to retain. "
            "Supersedes --languages."
        ),
    )
    parser.add_argument(
        "-S",
        "--no-subtitles",
        action="store_false",
        dest="subtitles",
        help=(
            "If no subtitles match the languages to retain, strip all subtitles. "
            "By default nudebomb keeps all subtitles if no subtitles match specified "
            "languages."
        ),
    )
    parser.add_argument(
        "-i",
        "--ignore",
        action=CommaListAction,
        dest="ignore",
        help="List of globs to ignore.",
    )
    parser.add_argument(
        "-L",
        "--no-symlinks",
        action="store_false",
        dest="symlinks",
        help="Do not follow symlinks for files and directories",
    )
    parser.add_argument(
        "-T",
        "--no-title",
        action="store_false",
        dest="title",
        help="Do not rewrite the metadata title with the filename stem when remuxing.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="Verbose output. Can be used multiple times for noisier output.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_const",
        dest="verbose",
        const=0,
        help="Display little to no output.",
    )
    parser.add_argument(
        "-r",
        "--recurse",
        action="store_true",
        help="Recurse through all paths on the command line.",
    )
    parser.add_argument(
        "-t",
        "--timestamps",
        action="store_true",
        help=(
            "Read and write timestamps to strip only files that have been "
            "modified since the last run."
        ),
    )
    parser.add_argument(
        "-C",
        "--timestamps-no-check-config",
        dest="timestamps_check_config",
        action="store_false",
        default=True,
        help="Do not compare program config options with loaded timestamps.",
    )
    parser.add_argument(
        "-c", "--config", action="store", help="Alternate config file path"
    )
    parser.add_argument(
        "--tmdb-api-key",
        action="store",
        help=(
            "TMDB API key for online language lookup. Look up the original "
            "language of media files on TMDB when no lang file is found."
        ),
    )
    parser.add_argument(
        "--cache-expiry-days",
        action="store",
        type=int,
        help=(
            "Number of days before cache entries with no language found expire "
            "and are re-queried. Default: 30. Entries with a language never expire."
        ),
    )
    parser.add_argument(
        "--tvdb-api-key",
        action="store",
        help=(
            "TVDB API key for online TV series language lookup. "
            "Look up the original language of TV series on TVDB "
            "when no lang file is found."
        ),
    )
    parser.add_argument(
        "-A",
        "--after",
        action="store",
        dest="after",
        help=(
            "Only strip mkvs after the specified timestamp. "
            "Supersedes recorded timestamp files. Can be an epoch number or "
            "datetime string."
        ),
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {VERSION}"
    )
    parser.add_argument(
        "paths",
        metavar="path",
        type=str,
        nargs="+",
        help="Where your MKV files are stored. Can be a directories or files.",
    )

    # Parse the list of given arguments
    if params is not None:
        params = params[1:]
    nns = parser.parse_args(params)

    # increment verbose
    if nns.verbose is None:
        nns.verbose = 1
    elif nns.verbose > 0:
        nns.verbose += 1

    return Namespace(nudebomb=nns)


def main(args: tuple[str, ...] | None = None) -> None:
    """Process command line arguments, config and walk inputs."""
    arguments = get_arguments(args)
    setup_logging(arguments.nudebomb.verbose)
    config = NudebombConfig().get_config(arguments)
    # Iterate over all found mkv files
    walker = Walk(config)
    walker.run()


if __name__ == "__main__":
    main()
