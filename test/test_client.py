#!/usr/bin/env python3
"""
Simple test client for Trust Engine v2 API.

Usage:
    python test/test_client.py
    python test/test_client.py --input test/example_article.json
    python test/test_client.py --url https://your-api.run.app
"""

import argparse
import json
import sys
from pathlib import Path

import requests


def load_article(filepath: str) -> dict:
    """Load article from JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_article(api_url: str, article: dict) -> list:
    """Send article to API for analysis."""
    endpoint = f"{api_url}/api/v1/analyze"

    print(f"Sending article to {endpoint}...")
    print(f"Title: {article['title']}")
    print(f"Author: {article['author']}")
    print(f"Length: {len(article['body'])} characters\n")

    try:
        response = requests.post(endpoint, json=article, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def print_results(metrics: list):
    """Print analysis results in a readable format."""
    print("=" * 80)
    print("ANALYSIS RESULTS")
    print("=" * 80)

    for metric in metrics:
        flag_symbol = "✓" if metric["flag"] == 1 else "✗" if metric["flag"] == -1 else "○"
        flag_color = "\033[92m" if metric["flag"] == 1 else "\033[91m" if metric["flag"] == -1 else "\033[93m"
        reset_color = "\033[0m"

        print(f"\n{flag_color}{flag_symbol} {metric['criteria_name']}{reset_color}")
        print(f"   Score: {metric['score']:.2f}/1.00")
        print(f"   {metric['explanation']}")

    print("\n" + "=" * 80)

    # Calculate overall score
    avg_score = sum(m["score"] for m in metrics) / len(metrics)
    print(f"Overall Score: {avg_score:.2f}/1.00")
    print("=" * 80)


def save_results(metrics: list, output_path: str):
    """Save results to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Test client for Trust Engine v2 API"
    )
    parser.add_argument(
        "--input",
        "-i",
        default="test/example_article.json",
        help="Path to input JSON file with article data",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Path to save results (optional)",
    )
    parser.add_argument(
        "--url",
        "-u",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    # Check if API is running
    try:
        health_response = requests.get(f"{args.url}/health", timeout=5)
        if health_response.status_code != 200:
            print(f"Warning: API health check failed at {args.url}", file=sys.stderr)
    except requests.exceptions.RequestException:
        print(f"Error: Cannot connect to API at {args.url}", file=sys.stderr)
        print("Make sure the API is running:", file=sys.stderr)
        print("  uvicorn trust_api.main:app --reload", file=sys.stderr)
        sys.exit(1)

    # Load and analyze article
    article = load_article(args.input)
    metrics = analyze_article(args.url, article)

    # Display results
    print_results(metrics)

    # Save results if requested
    if args.output:
        save_results(metrics, args.output)


if __name__ == "__main__":
    main()
