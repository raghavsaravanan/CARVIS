"""Authentication for the CARVIS /v1 API (M2 B2a, ADR-0002).

- :mod:`auth.jwks`: bounded JWKS cache (asymmetric keys only).
- :mod:`auth.tokens`: token verification into a :class:`auth.tokens.Principal`.

B2c wires them into the ``/v1`` auth dependency (:mod:`api_v1.auth`).
"""
