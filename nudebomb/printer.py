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
        self.message(message, attrs=["dark"])

    def skip_already_optimized(self, message):
        """Skip already optimized."""
        attrs = ["dark"] if self._verbose > 1 else ["bold"]
        self.message(message, "green", attrs=attrs)

    def print_info(self, languages: tuple | list, sub_languages: tuple | list):
        """Print mkv info."""
        langs = ", ".join(sorted(languages))
        audio = "audio " if sub_languages else ""
        self.message(f"Stripping {audio}languages except {langs}.", force_verbose=True)
        if sub_languages:
            sub_langs = ", ".join(sorted(sub_languages))
            cprint(f"Stripping subtitle languages except {sub_langs}.")
        cprint("Searching for MKV files to process", end="")
        if self._verbose > 1:
            cprint(":")
            self._last_verbose_message = True
        else:
            self._last_verbose_message = False

    def container_repacking_done(self):
        """Only done for repack if very verbose."""
        if self._verbose > 1:
            self.done()

    def copied_message(self):
        """Dot for copied file."""
        self.skip_message("")

    def dry_run(self, message):
        """Dry run message."""
        self.message(message, "black", attrs=["bold"], force_verbose=True)

    def keeping_langs(self, message):
        """Keep languages config message."""
        self.message(message, "cyan")

    def packed_message(self):
        """Dot for repacked file."""
        self.message("")

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
        self.message(message, color="yellow", force_verbose=True)

    def error(self, message: str, exc: Exception | None = None):
        """Error."""
        message = "ERROR: " + message
        if exc:
            message += f": {exc}"
        self.message(message, color="red", force_verbose=True)
