"""Wrapper: monkey-patch eventlet BEFORE importing songwalk package."""

import eventlet

eventlet.monkey_patch()

from songwalk.__main__ import main

if __name__ == "__main__":
    main()
