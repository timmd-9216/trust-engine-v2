#!/usr/bin/env python3
"""
Script to check Information Tracer API quota/usage status.

This helps understand if there are quota issues and plan accordingly.
"""

import os
import sys

from dotenv import load_dotenv

try:
    from trust_api.scrapping_tools.information_tracer import check_api_usage
except ImportError:
    print("Error: trust_api module not found. Run from project root with poetry.")
    sys.exit(1)

load_dotenv()


def main() -> int:
    """Check API usage/quota."""
    api_key = os.getenv("INFORMATION_TRACER_API_KEY")

    if not api_key:
        print("Error: INFORMATION_TRACER_API_KEY not found in environment", file=sys.stderr)
        return 1

    print("Checking Information Tracer API usage/quota...\n")

    try:
        usage = check_api_usage(api_key)

        print("API Usage/Quota Information:")
        print("=" * 60)

        # Pretty print the response
        if isinstance(usage, dict):
            for key, value in usage.items():
                print(f"  {key}: {value}")
        else:
            print(f"  {usage}")

        print("\n" + "=" * 60)
        print("\nAnalysis:")

        # Common quota fields to check
        if isinstance(usage, dict):
            # Check for quota-related fields
            quota_fields = [
                "quota",
                "limit",
                "used",
                "remaining",
                "daily_limit",
                "daily_used",
                "monthly_limit",
                "monthly_used",
                "requests_remaining",
                "requests_limit",
            ]

            found_quota_info = False
            for field in quota_fields:
                if field in str(usage).lower():
                    found_quota_info = True
                    break

            if not found_quota_info:
                print("  ⚠️  No clear quota information found in response")
                print("     (This is normal - Information Tracer might not expose quota via API)")

            # Check for error fields
            if "error" in usage:
                print(f"  ❌ Error: {usage['error']}")
                return 1

        print("  ✓ API is accessible")
        print("\nRecommendations:")
        print("  - If you see quota/limit information, monitor it regularly")
        print("  - If many jobs failed on 2026-01-08, it was likely a quota issue")
        print("  - Current failed jobs from that date should be safe to keep for 30 days")

        return 0

    except Exception as e:
        print(f"Error checking API usage: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
