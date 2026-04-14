"""Base parser interface for investment report PDFs."""

from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Abstract base class for PDF parsers.

    Each broker (Warren, XP, BTG, etc.) should have its own parser
    that implements this interface.
    """

    @abstractmethod
    def parse(self, pdf_path: str) -> list[dict]:
        """Parse a PDF investment report and extract asset positions.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            List of dicts with keys:
                - name (str): Asset name as it appears in the PDF
                - value (float): Current gross value (Saldo Bruto)
                - source (str): Source identifier, e.g. "warren", "xp"
        """
        raise NotImplementedError

    @staticmethod
    def parse_brazilian_number(text: str) -> float | None:
        """Parse a Brazilian-format number string to float.

        Examples:
            "889.309,06" -> 889309.06
            "1.234,56" -> 1234.56
            "42,00" -> 42.0
            "-7.369,59" -> -7369.59
            "R$ 1.000,00" -> 1000.0
        """
        if not text or not text.strip():
            return None
        text = text.strip().replace("R$", "").strip()
        # Remove thousand separators (dots) and convert decimal comma
        text = text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None
