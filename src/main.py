"""Main entry point for the TermiReq application.

This simple script delegates execution directly to the `main()` function
inside `src.cli`. It allows the application to be invoked safely via
`python -m src.main` without side effects upon import.
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
