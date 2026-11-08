# Carvis acceptance evidence

`test_specs_v2.py` contains a minimal transcription of the engine-oil rows in
`wrxOilAmount.pdf`, page 1, SPECIFICATIONS > WRX / CAPACITY. The original PDF
was rendered and visually inspected during implementation. Its engine-oil cells
span both 6MT and CVT columns: replacement with filter is 4.5 L (4.8 US qt,
4.0 Imp qt); replacement of oil only is 4.3 L (4.5 US qt, 3.8 Imp qt).
Overhaul capacity is a separate operation. PDFs remain outside Git.

All divergent capacity, fastener, conflicting-manual, procedure and review-PDF
fixtures are explicitly **synthetic**. They test isolation and refusal behavior;
their numbers must never be ingested into a production collection.

`wrx-acceptance.json` is a source-bound acceptance suite for the four oil-change
variants and safe refusals. It uses the actual supplied PDF's SHA-256 and original
data-row positions (3 for oil/filter, 4 for oil only). It does not authorize review
status or production activation. Run it against staging only after source review.

`wheelHeightSpec.pdf` was also rendered. It contains suspension-height data and
camber setup instructions, with no wheel-fastener torque specification. A positive
WRX wheel-torque acceptance case still requires the original tire/wheel installation
manual page, confirmed applicability, and source review. The old database text
alone is insufficient evidence to approve this value.
