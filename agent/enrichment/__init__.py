"""Signal enrichment pipeline.

Four primary sources feed the hiring_signal_brief + competitor_gap_brief:
    - Crunchbase ODM sample (firmographics, funding, leadership)
    - Public job posts (Playwright, no login, robots.txt respected)
    - layoffs.fyi CSV
    - Leadership-change detection (Crunchbase news + public press)

AI-maturity scoring consumes those inputs and emits a 0-3 score with
per-signal justification and confidence. The `pipeline` module merges
everything into a single brief that matches `data/schemas/hiring_signal_brief.schema.json`.
"""
