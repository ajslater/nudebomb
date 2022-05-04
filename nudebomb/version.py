"""Package name and version."""

import pkg_resources


PROGRAM_NAME = "nudebomb"
try:
    DISTRIBUTION = pkg_resources.get_distribution(PROGRAM_NAME)
    VERSION = DISTRIBUTION.version
except pkg_resources.DistributionNotFound:
    VERSION = "dev"
