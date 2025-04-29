"""Print Messages."""

from termcolor import cprint


class Printer:
    """Printing messages during walk and handling."""

    def __init__(self, verbose: int):
        """Initialize verbosity and flags."""
        self._verbose = verbose
        self._last_verbose_message = True

    def message(
        self, reason, color="white", attrs=None, *, force_verbose=False, end="\n"
    ):
        """Print a dot or skip message."""
        if self._verbose < 1:
            return
        if (self._verbose == 1 and not force_verbose) or not reason:
            cprint(".", color, attrs=attrs, end="", flush=True)
            self._last_verbose_message = False
            return
        if not self._last_verbose_message:
            reason = "\n" + reason
        attrs = attrs if attrs else []
        cprint(reason, color, attrs=attrs, end=end, flush=True)
        if end:
            self._last_verbose_message = True

    def skip_message(self, message):
        """Skip Message."""
        self.message(message, color="dark_grey")

    def skip_timestamp_message(self, message):
        """Skip by timestamp."""
        self.message(message, color="light_green", attrs=["dark", "bold"])

    def skip_already_optimized(self, message):
        """Skip already optimized."""
        self.message(message, "green")

    def extra_message(self, message):
        """High verbosity messages."""
        if self._verbose > 2:  # noqa: PLR2004
            self.message(message, color="dark_grey", attrs=["bold"])

    def config(self, message):
        """Keep languages config message."""
        self.message(message, "cyan", force_verbose=True)

    def print_config(self, languages: tuple | list, sub_languages: tuple | list):
        """Print mkv info."""
        langs = ", ".join(sorted(languages))
        audio = "audio " if sub_languages else ""
        self.config(f"Stripping {audio}languages except {langs}.")
        if sub_languages:
            sub_langs = ", ".join(sorted(sub_languages))
            self.config(f"Stripping subtitle languages except {sub_langs}.")

    def start_operation(self):
        """Start searching method."""
        cprint("Searching for MKV files to process", end="")
        if self._verbose > 1:
            cprint(":")
            self._last_verbose_message = True
        else:
            self._last_verbose_message = False

    def dry_run(self, message):
        """Dry run message."""
        self.message(message, "dark_grey", attrs=["bold"], force_verbose=True)

    def done(self):
        """Operation done."""
        if self._verbose:
            cprint("done.")
            self._last_verbose_message = True

    def warn(self, message: str, exc: Exception | None = None):
        """Warning."""
        message = "WARNING: " + message
        if exc:
            message += f": {exc}"
        self._last_verbose_message = False
        self.message(message, color="light_yellow", force_verbose=True)

    def error(self, message: str, exc: Exception | None = None):
        """Error."""
        message = "ERROR: " + message
        if exc:
            message += f": {exc}"
        self.message(message, color="light_red", force_verbose=True)
