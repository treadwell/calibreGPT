#!/usr/bin/env python3

import argparse
import json
import os
import time

from migration_utils import load_libraries, migrate_once, migration_status


def main() -> int:
    parser = argparse.ArgumentParser(prog="migrate_multi_library")
    parser.add_argument("--engine", default="./engine.py")
    parser.add_argument("--libraries-file")
    parser.add_argument("--library-path", action="append", default=[])
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--active-model", default="text-embedding-ada-002")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--sleep-seconds", type=int, default=2)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    libraries = load_libraries(args.libraries_file, args.library_path)
    engine_path = os.path.abspath(args.engine)
    if not os.path.exists(engine_path):
        raise ValueError(f"Engine not found: {engine_path}")

    cycle = 0
    while True:
        cycle += 1
        all_complete = True
        print(f"\n== Cycle {cycle} ==")
        for library in libraries:
            status = migration_status(
                engine_path=engine_path,
                library_path=library,
                embedding_model=args.embedding_model,
                active_model=args.active_model,
                batch_size=args.batch_size,
            )
            print(f"[status] {library} :: {json.dumps(status)}")
            if status["remaining"] > 0:
                all_complete = False
                if not args.status_only:
                    migrated = migrate_once(
                        engine_path=engine_path,
                        library_path=library,
                        embedding_model=args.embedding_model,
                        active_model=args.active_model,
                        batch_size=args.batch_size,
                    )
                    print(f"[migrate] {library} :: {json.dumps(migrated)}")

        if args.status_only:
            return 0
        if all_complete:
            print("All libraries are complete.")
            return 0
        if args.max_cycles and cycle >= args.max_cycles:
            print(f"Reached max cycles: {args.max_cycles}")
            return 0
        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
