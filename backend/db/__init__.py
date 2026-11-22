"""PostgreSQL foundation for the Carvis API (M2 Track B1, ADR-0001).

- :mod:`db.engine`: the application engine and session factory (no route uses them in B1) and the
  libpq connection string used by the readiness probe.
- :mod:`db.readiness`: the bounded, single-flight ``/readyz`` probe.
- :mod:`db.history`: the linear-history check for the Alembic chain.
- :mod:`db.roles`: role names, markers and the owner context used by migrations.
"""
