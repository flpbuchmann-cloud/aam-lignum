"""Placeholder parsers for brokers not yet implemented.

Registered so they appear in the UI dropdown. Selecting one and trying
to parse raises a friendly message until a real parser is built.
"""

from .base import BaseParser


class _PendingParser(BaseParser):
    broker_name: str = ""

    def parse(self, pdf_path: str) -> list[dict]:
        raise NotImplementedError(
            f"Parser de {self.broker_name} ainda nao implementado. "
            f"Envie um PDF de exemplo para que o parser seja desenvolvido."
        )


class ItauParser(_PendingParser):
    broker_name = "Itau"


class BradescoParser(_PendingParser):
    broker_name = "Bradesco"


class BTGParser(_PendingParser):
    broker_name = "BTG"
