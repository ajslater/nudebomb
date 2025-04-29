"""Print Messages."""

from termcolor import cprint


class Printer:
    """Printing messages during walk and handling."""

    def __init__(self, verbose: int):
        """Initialize verbosity and flags."""
        self._verbose = verbose
        self._after_newline = True

    def _message(
        self, reason, color="white", attrs=None, *, force_verbose=False, end="\n"
    ):
        """Print a dot or skip message."""
        if self._verbose < 1:
            return
        if (self._verbose == 1 and not force_verbose) or not reason:
            cprint(".", color, attrs=attrs, end="", flush=True)
            self._after_newline = False
            return
        if not self._after_newline:
            reason = "\n" + reason
        attrs = attrs if attrs else []
        cprint(reason, color, attrs=attrs, end=end, flush=True)
        if end:
            self._after_newline = True

    def skip(self, message, path):
        """Skip Message."""
        parts = ["Skip", message, str(path)]
        message = ": ".join(parts)
        self._message(message, color="dark_grey")

    def skip_timestamp(self, message):
        """Skip by timestamp."""
        self._message(message, color="light_green", attrs=["dark", "bold"])

    def skip_already_optimized(self, message):
        """Skip already optimized."""
        self._message(message, "green")

    def extra_info(self, message):
        """High verbosity messages."""
        if self._verbose > 2:  # noqa: PLR2004
            self._message(message, color="dark_grey", attrs=["bold"])

    def config(self, message):
        """Keep languages config message."""
        self._message(message, "cyan", force_verbose=True)

    def print_config(self, languages: tuple | list, sub_languages: tuple | list):
        """Print mkv info."""
        langs = ", ".join(sorted(languages))
        audio = "audio " if sub_languages else ""
        self.config(f"Stripping {audio}languages except {langs}.")
        if sub_languages:
            sub_langs = ", ".join(sorted(sub_languages))
            self.config(f"Stripping subtitle languages except {sub_langs}.")

    def work_manifest(self, message):
        """Work manifest for what we plan to do to the mkv."""
        self._message(message, force_verbose=True)

    def start_operation(self):
        """Start searching method."""
        cprint("Searching for MKV files to process", end="")
        if self._verbose > 1:
            cprint(":")
            self._after_newline = True
        else:
            self._after_newline = False

    def dry_run(self, message):
        """Dry run message."""
        self._message(message, "dark_grey", attrs=["bold"], force_verbose=True)

    def done(self):
        """Operation done."""
        if self._verbose:
            cprint("done.")
            self._after_newline = True

    def warn(self, message: str, exc: Exception | None = None):
        """Warning."""
        message = "WARNING: " + message
        if exc:
            message += f": {exc}"
        self._after_newline = False
        self._message(message, color="light_yellow", force_verbose=True)

    def error(self, message: str, exc: Exception | None = None):
        """Error."""
        message = "ERROR: " + message
        if exc:
            message += f": {exc}"
        self._message(message, color="light_red", force_verbose=True)
