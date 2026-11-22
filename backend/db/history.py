"""Linear-history check for the Alembic chain (M2 Track B1; doc 08 invariant 7).

``python -m db.history`` (from ``backend/``) exits non-zero unless the chain has exactly one head,
one base, and no merge or branch point. CI runs it; the test suite also runs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "migrations" / "alembic.ini"


class HistoryError(RuntimeError):
    """The Alembic chain is not a single linear history."""


def script_directory(ini: Path = ALEMBIC_INI) -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ini)))


def check_linear_history(scripts: ScriptDirectory) -> str:
    """Return the single head, or raise :class:`HistoryError`."""
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise HistoryError(f"expected exactly one Alembic head, found {len(heads)}: {', '.join(sorted(heads))}")
    bases = scripts.get_bases()
    if len(bases) != 1:
        raise HistoryError(f"expected exactly one Alembic base, found {len(bases)}")
    children: dict[str, int] = {}
    for revision in scripts.walk_revisions():
        down = revision.down_revision
        downs = () if down is None else (down,) if isinstance(down, str) else tuple(down)
        if len(downs) > 1:
            raise HistoryError(f"revision {revision.revision} is a merge point")
        if revision.dependencies:
            raise HistoryError(f"revision {revision.revision} declares depends_on")
        for parent in downs:
            children[parent] = children.get(parent, 0) + 1
    branched = sorted(rev for rev, count in children.items() if count > 1)
    if branched:
        raise HistoryError(f"revision {branched[0]} is a branch point")
    return heads[0]


def main() -> int:
    try:
        head = check_linear_history(script_directory())
    except HistoryError as exc:
        print(f"Alembic history check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Alembic history is linear; head {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
