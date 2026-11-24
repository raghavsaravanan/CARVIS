"""The versioned ``/v1`` API (M2 B2c; ADR-0004, contract ``docs/architecture/05-api-v1.md``).

- :mod:`api_v1.errors`: the error envelope, ``/v1``-scoped handlers, route class and ``no-store`` middleware.
- :mod:`api_v1.auth`: the request runtime, bearer parsing, runtime-login gate and caller dependency.
- :mod:`api_v1.routes`: ``GET /v1/me`` and ``GET /v1/workspaces``.
"""
