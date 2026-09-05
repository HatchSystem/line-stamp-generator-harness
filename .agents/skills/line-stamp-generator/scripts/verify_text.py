#!/usr/bin/env python3
"""Stable public entrypoint for AI text evidence generation."""
from __future__ import annotations

from text_evidence import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
