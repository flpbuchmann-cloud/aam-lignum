"""Formatting utilities for the dashboard."""


def format_brl(value: float) -> str:
    """Format a number as Brazilian Real currency."""
    if value < 0:
        return f"-R$ {abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_pct(value: float) -> str:
    """Format a number as percentage."""
    return f"{value:.2f}%"
