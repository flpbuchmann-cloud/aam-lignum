"""Parser registry for multiple broker PDF formats."""

from .base import BaseParser
from .warren import WarrenParserV2
from .xp import XPParser
from .stubs import ItauParser, BradescoParser, BTGParser

PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "Warren": WarrenParserV2,
    "XP": XPParser,
    "Itau": ItauParser,
    "Bradesco": BradescoParser,
    "BTG": BTGParser,
}


def get_parser(broker: str) -> BaseParser:
    """Get a parser instance for the given broker."""
    cls = PARSER_REGISTRY.get(broker)
    if cls is None:
        raise ValueError(f"No parser available for broker: {broker}")
    return cls()


def available_brokers() -> list[str]:
    """Return list of supported broker names."""
    return list(PARSER_REGISTRY.keys())
