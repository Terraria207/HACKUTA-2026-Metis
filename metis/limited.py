"""Exec a controlled command with bounded output; avoids preexec_fn in threaded server."""

import os
import resource
import sys

if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    os.execvp(sys.argv[1], sys.argv[1:])
