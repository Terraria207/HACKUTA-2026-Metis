"""Exec a controlled command with bounded output; avoids preexec_fn in threaded server.
Used only for the Docker Lean sandbox, which needs a Linux host."""

import os
import sys

if __name__ == "__main__":
    try:
        import resource
    except ImportError:  # Windows: no file-size limit available; the sandbox itself is Linux-only
        resource = None
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    os.execvp(sys.argv[1], sys.argv[1:])
