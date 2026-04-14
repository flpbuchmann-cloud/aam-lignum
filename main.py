"""CLI entry point for AAM Lignum.

Usage:
    python main.py parse <pdf_path> [--broker BROKER]   Parse a PDF and show extracted assets
    python main.py match <pdf_path> [--broker BROKER]   Parse + match against registry
    python main.py push <pdf_path> [--broker BROKER]    Parse + match + push unmatched to Sheets
    python main.py dashboard                            Launch Streamlit dashboard
    python main.py registry [--refresh]                 Show registry contents
"""

import argparse
import sys
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers import get_parser, available_brokers
from src.matching.registry import AssetRegistry
from src.matching.engine import MatchingEngine


def format_brl(value: float) -> str:
    """Format number as BRL."""
    if value < 0:
        return f"-R$ {abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _get_parser_for_args(args):
    """Get the parser based on CLI args."""
    broker = getattr(args, "broker", "Warren")
    return get_parser(broker)


def cmd_parse(args):
    """Parse a PDF and display extracted assets."""
    pdf_path = args.pdf_path
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    print(f"Parsing: {pdf_path}")
    print("=" * 80)

    parser = _get_parser_for_args(args)
    assets = parser.parse(pdf_path)

    total = 0.0
    print(f"{'#':<4} {'Asset Name':<55} {'Value':>15}")
    print("-" * 80)

    for i, asset in enumerate(assets, 1):
        name = asset["name"][:55]
        value = asset["value"]
        total += value
        print(f"{i:<4} {name:<55} {format_brl(value):>15}")

    print("-" * 80)
    print(f"{'':4} {'TOTAL':<55} {format_brl(total):>15}")
    print(f"\n{len(assets)} assets extracted.")


def cmd_match(args):
    """Parse a PDF and match against the registry."""
    pdf_path = args.pdf_path
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    print(f"Parsing: {pdf_path}")
    parser = _get_parser_for_args(args)
    assets = parser.parse(pdf_path)

    print("Loading registry...")
    engine = MatchingEngine()
    results = engine.match(assets)
    summary = engine.get_summary(results)

    print(f"\n{'=' * 100}")
    print("MATCHING RESULTS")
    print(f"{'=' * 100}")
    print(f"Total assets:    {summary['total']}")
    print(f"Exact matches:   {len(summary['exact'])}")
    print(f"Fuzzy matches:   {len(summary['fuzzy'])}")
    print(f"Manual matches:  {len(summary['manual'])}")
    print(f"Unmatched:       {len(summary['unmatched'])}")
    print(f"Total value:     {format_brl(summary['total_value'])}")
    print(f"Matched value:   {format_brl(summary['matched_value'])}")
    print(f"Unmatched value: {format_brl(summary['unmatched_value'])}")

    if summary["exact"]:
        print("\n--- EXACT MATCHES ---")
        for r in summary["exact"]:
            print(f"  [{r.pdf_name}]")
            print(f"    -> {r.nome_1}  |  {r.macro_classe}  |  {format_brl(r.value)}")

    if summary["fuzzy"]:
        print("\n--- FUZZY MATCHES ---")
        for r in summary["fuzzy"]:
            print(f"  [{r.pdf_name}]")
            print(f"    -> {r.nome_1}  ({r.confidence:.0%})  |  {r.macro_classe}  |  {format_brl(r.value)}")

    if summary["unmatched"]:
        print("\n--- UNMATCHED ---")
        for r in summary["unmatched"]:
            print(f"  [{r.pdf_name}]  |  {format_brl(r.value)}")
            if r.fuzzy_candidates:
                for c in r.fuzzy_candidates[:3]:
                    print(f"    ? {c['nome']}  ({c['score']:.0%})")

    table = engine.build_allocation_table(results)
    print(f"\n{'=' * 100}")
    print("ASSET ALLOCATION TABLE")
    print(f"{'=' * 100}")

    print(f"\n{'#':<4} {'Asset':<50} {'Value':>15} {'% PL':>8} {'Macro Classe':<20}")
    print("-" * 100)

    for i, row in enumerate(table, 1):
        name = row["nome_1"][:50]
        print(f"{i:<4} {name:<50} {format_brl(row['value']):>15} {row['pct_pl']:>7.2f}% {row['macro_classe']:<20}")

    total_pl = sum(r["value"] for r in table)
    print("-" * 100)
    print(f"{'':4} {'TOTAL':<50} {format_brl(total_pl):>15} {'100.00%':>8}")


def cmd_push(args):
    """Parse, match, and push unmatched names to Google Sheets."""
    pdf_path = args.pdf_path
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    from src.sheets.client import SheetsClient

    print(f"Parsing: {pdf_path}")
    parser = _get_parser_for_args(args)
    assets = parser.parse(pdf_path)

    print("Loading registry...")
    client = SheetsClient()
    registry = AssetRegistry()
    if client.is_authenticated or client._authenticate():
        registry.load(sheets_client=client)
    else:
        registry.load()

    engine = MatchingEngine(registry)
    results = engine.match(assets)
    summary = engine.get_summary(results)

    unmatched_names = [r.pdf_name for r in summary["unmatched"]]
    print(f"\nTotal: {summary['total']} | Matched: {summary['total'] - len(unmatched_names)} | Unmatched: {len(unmatched_names)}")

    if not unmatched_names:
        print("Todos os ativos tem match. Nada para enviar.")
        return

    print(f"\nNomes sem match:")
    for name in unmatched_names:
        print(f"  - {name}")

    if not client.is_authenticated:
        print("\nErro: credentials.json nao encontrado. Configure para enviar ao Google Sheets.")
        return

    count = client.push_unmatched_names(unmatched_names)
    print(f"\n{count} nome(s) enviado(s) para a Base de Dados.")


def cmd_dashboard(args):
    """Launch the Streamlit dashboard."""
    import subprocess
    app_path = PROJECT_ROOT / "src" / "dashboard" / "app.py"
    print(f"Launching dashboard: {app_path}")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], cwd=str(PROJECT_ROOT))


def cmd_registry(args):
    """Show registry contents."""
    registry = AssetRegistry()
    registry.load(force_refresh=args.refresh)

    print(f"Asset Registry: {len(registry)} assets")
    print(f"{'=' * 100}")
    print(f"{'#':<4} {'Nome':<45} {'Nome 1':<35} {'Macro':<15} {'Codigo':<12}")
    print("-" * 100)

    for i, asset in enumerate(registry.assets, 1):
        nome = asset["nome"][:45]
        nome_1 = asset["nome_1"][:35]
        macro = asset["macro_classe"][:15]
        code = asset["codigo_interno"][:12]
        print(f"{i:<4} {nome:<45} {nome_1:<35} {macro:<15} {code:<12}")


def main():
    parser = argparse.ArgumentParser(
        description="AAM Lignum - CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    brokers = available_brokers()

    # parse command
    p_parse = subparsers.add_parser("parse", help="Parse a PDF and show extracted assets")
    p_parse.add_argument("pdf_path", help="Path to the PDF file")
    p_parse.add_argument("--broker", choices=brokers, default="Warren", help="Broker name")
    p_parse.set_defaults(func=cmd_parse)

    # match command
    p_match = subparsers.add_parser("match", help="Parse PDF and match against registry")
    p_match.add_argument("pdf_path", help="Path to the PDF file")
    p_match.add_argument("--broker", choices=brokers, default="Warren", help="Broker name")
    p_match.set_defaults(func=cmd_match)

    # push command
    p_push = subparsers.add_parser("push", help="Parse + match + push unmatched to Google Sheets")
    p_push.add_argument("pdf_path", help="Path to the PDF file")
    p_push.add_argument("--broker", choices=brokers, default="Warren", help="Broker name")
    p_push.set_defaults(func=cmd_push)

    # dashboard command
    p_dash = subparsers.add_parser("dashboard", help="Launch Streamlit dashboard")
    p_dash.set_defaults(func=cmd_dashboard)

    # registry command
    p_reg = subparsers.add_parser("registry", help="Show registry contents")
    p_reg.add_argument("--refresh", action="store_true", help="Force refresh from Google Sheets")
    p_reg.set_defaults(func=cmd_registry)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
