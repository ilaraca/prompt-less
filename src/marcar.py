"""Shim legado: use src.repos.marcar."""
from src.repos.marcar import *  # noqa: F403
from src.repos.marcar import main

if __name__ == "__main__":
    main()
