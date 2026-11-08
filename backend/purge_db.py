"""Carvis compatibility entry point: destructive purge has been retired."""


def main():
    raise SystemExit("Purge is disabled. Use qdrant_v2.py and migrate_v2.py; existing collections remain intact.")


if __name__ == "__main__":
    main()
