#!/usr/bin/env python3
""" pdf_creator.py module (DECOMMISSIONED)

This module used to generate PDF reports and PNG charts from the cleaned data.

It has been decommissioned because:
- fpdf (for PDF) was removed
- matplotlib (required for pandas .plot.scatter) is not a project dependency
- The pipeline no longer calls it (see main.py)

The function is kept as a no-op stub to prevent import/call errors during transition.
It can be fully removed in a future cleanup.

See docs/m6-dynamic-page-count-action-plan.md Item 10/11 context.
"""

def pdf_creator_main(city_name: str = None):
    """Main module function (decommissioned no-op).

    This call is intentionally a no-op to avoid requiring matplotlib
    and to decommission PDF/chart generation from the daily pipeline.
    """
    if city_name:
        log = __import__('logging').getLogger(__name__)
        log.info(f"pdf_creator_main called for city: {city_name} (decommissioned - no-op)")
    print("Debug info: pdf_creator_main is decommissioned (no output generated).")


# All plotting / PDF generation code has been removed.
# The functions below were previously used but are no longer needed.

if __name__ == "__main__":
    pdf_creator_main()
