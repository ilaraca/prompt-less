"""Shim legado: use src.planning.plan_repos."""
from src.planning.plan_repos import *  # noqa: F403
from src.planning.plan_repos import main

if __name__ == "__main__":
    main()
