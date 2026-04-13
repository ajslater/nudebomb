"""Package name and version."""

from importlib.metadata import PackageNotFoundError, version

PROGRAM_NAME = PACKAGE_NAME = "nudebomb"


def get_version() -> str:
    """Get the current installed nudebomb version."""
    try:
        v = version(PACKAGE_NAME)
    except PackageNotFoundError:
        v = "dev"
    return v


VERSION = get_version()
