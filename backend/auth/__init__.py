"""Authentication for the CARVIS /v1 API (M2 B2a, ADR-0002).

- :mod:`auth.jwks`: bounded JWKS cache (asymmetric keys only).
- :mod:`auth.tokens`: token verification into a :class:`auth.tokens.Principal`.

Not wired to any route in B2a; B2c adds the ``/v1`` auth dependency.
"""
