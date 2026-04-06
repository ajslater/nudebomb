"""Print Messages."""

from termcolor import cprint


class Printer:
    """Printing messages during walk and handling."""

    def __init__(self, verbose: int) -> None:
        """Initialize verbosity and flags."""
        self._verbose: int = verbose
        self._after_newline: bool = True

    def _message(
        self,
        reason: str,
        color: str = "white",
        attrs: list[str] | None = None,
        *,
        force_verbose: bool = False,
        end: str = "\n",
        char: str = ".",
    ) -> None:
        """Print a dot or skip message."""
        if self._verbose < 1:
            return
        if (self._verbose == 1 and not force_verbose) or not reason:
            cprint(char, color, attrs=attrs, end="", flush=True)
            self._after_newline = False
            return
        if not self._after_newline:
            reason = "\n" + reason
        attrs = attrs or []
        cprint(reason, color, attrs=attrs, end=end, flush=True)
        if end:
            self._after_newline = True

    def skip(self, message: str, path) -> None:
        """Skip Message."""
        parts = ["Skip", message, str(path)]
        message = ": ".join(parts)
        self._message(message, color="dark_grey")

    def skip_timestamp(self, message: str) -> None:
        """Skip by timestamp."""
        self._message(message, color="light_green", attrs=["dark", "bold"])

    def skip_already_optimized(self, message) -> None:
        """Skip already optimized."""
        self._message(message, "green")

    def extra_info(self, message: str) -> None:
        """High verbosity messages."""
        if self._verbose > 2:  # noqa: PLR2004
            self._message(message, color="dark_grey", attrs=["bold"])

    def config(self, message: str) -> None:
        """Keep languages config message."""
        self._message(message, "cyan", force_verbose=True)

    def tmdb_hit(self, message: str) -> None:
        """TMDB API lookup succeeded."""
        self._message(message, "cyan", force_verbose=True, char="O")

    def tmdb_cache_hit(self, message: str) -> None:
        """TMDB lookup succeeded from cache."""
        self._message(message, "green", force_verbose=True, char="o")

    def tmdb_no_result(self, message: str) -> None:
        """TMDB lookup returned no result or no language."""
        self._message(message, "light_yellow", force_verbose=True, char="x")

    def tmdb_rate_limited(self, message: str) -> None:
        """TMDB lookup failed due to API rate limiting."""
        self._message(message, "light_yellow", force_verbose=True, char="X")

    def tmdb_error(self, message: str) -> None:
        """TMDB lookup failed due to a network or server error."""
        self._message(message, "light_red", force_verbose=True, char="X")

    def print_config(
        self,
        languages: tuple | list,
        sub_languages: tuple | list,
    ) -> None:
        """Print mkv info."""
        langs = ", ".join(sorted(languages))
        audio = "audio " if sub_languages else ""
        self.config(f"Stripping {audio}languages except {langs}.")
        if sub_languages:
            sub_langs = ", ".join(sorted(sub_languages))
            self.config(f"Stripping subtitle languages except {sub_langs}.")

    def work_manifest(self, message: str) -> None:
        """Work manifest for what we plan to do to the mkv."""
        self._message(message, force_verbose=True)

    def start_operation(self) -> None:
        """Start searching method."""
        cprint("Searching for MKV files to process", end="")
        if self._verbose > 1:
            cprint(":")
            self._after_newline = True
        else:
            self._after_newline = False

    def dry_run(self, message: str) -> None:
        """Dry run message."""
        self._message(message, "dark_grey", attrs=["bold"], force_verbose=True)

    def done(self) -> None:
        """Operation done."""
        if self._verbose:
            cprint("done.")
            self._after_newline = True

    def warn(self, message: str, exc: Exception | None = None) -> None:
        """Warning."""
        message = "WARNING: " + message
        if exc:
            message += f": {exc}"
        self._after_newline = False
        self._message(message, color="light_yellow", force_verbose=True)

    def error(self, message: str, exc: Exception | None = None) -> None:
        """Error."""
        message = "ERROR: " + message
        if exc:
            message += f": {exc}"
        self._message(message, color="light_red", force_verbose=True)
