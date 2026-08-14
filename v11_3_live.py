#!/usr/bin/env python3
"""Compatibility entrypoint for the production V11 package.

The GitHub Actions workflow still calls this historical filename. All V11
logic now lives explicitly under v11/; no sitecustomize hook is required.
"""
from v11.runner import main, self_test

if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
