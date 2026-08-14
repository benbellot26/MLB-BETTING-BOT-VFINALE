from __future__ import annotations

from .methodology_v123 import install

install()

from . import train


if __name__ == "__main__":
    train.main()
