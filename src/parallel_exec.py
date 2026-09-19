"""Shim legado: use src.runtime.parallel_exec."""
from src.runtime.parallel_exec import *  # noqa: F403
from src.runtime.parallel_exec import main

if __name__ == "__main__":
    main()
