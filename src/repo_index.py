"""Shim legado: use src.repos.repo_index."""
from src.repos.repo_index import *  # noqa: F403
from src.repos.repo_index import main

if __name__ == "__main__":
    main()
