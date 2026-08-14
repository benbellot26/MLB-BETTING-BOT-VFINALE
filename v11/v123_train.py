from __future__ import annotations

from .v123_runtime import activate

activate()

from . import train


if __name__ == "__main__":
    train.main()
