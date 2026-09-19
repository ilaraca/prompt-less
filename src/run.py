"""Shim legado: use src.runtime.run."""
from src.runtime.run import *  # noqa: F403
from src.runtime.run import main

if __name__ == "__main__":
    main()
