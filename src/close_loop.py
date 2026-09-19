"""Shim legado: use src.executors.close_loop."""
from src.executors.close_loop import *  # noqa: F403
from src.executors.close_loop import main

if __name__ == "__main__":
    main()
