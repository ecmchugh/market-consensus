"""Ingestion — pull raw opinion items from pluggable sources.

Each source function returns a list of raw records in one shape:

    {
        "source":      "hackernews" | "reddit/r/<sub>",
        "source_type": "informed" | "crowd",
        "title":       str,
        "text":        str,
        "url":         str,
        "timestamp":   ISO-8601 str,
        "metadata":    dict,   # source-specific (points/author, etc.)
    }

Sources are pluggable and each item carries a `source_type` so a reading can be
sliced informed-only vs. crowd-only, and the divergence surfaced later.
"""
