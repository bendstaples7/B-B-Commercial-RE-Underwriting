"""
PDFParserService — extracts raw text and structured tables from an OM PDF.

Primary parser: PyMuPDF (fitz) for text extraction and table detection.
Fallback: pdfplumber for table extraction when PyMuPDF finds no tables.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7
"""

from __future__ import annotations

import io
import logging

from app.exceptions import InvalidFileError
from app.services.om_intake.om_intake_dataclasses import PDFExtractionResult

logger = logging.getLogger(__name__)


class PDFParserService:
    """Stateless service that extracts text and tables from a PDF byte string."""

    def extract(self, pdf_bytes: bytes) -> PDFExtractionResult:
        """Extract raw text and structured tables from *pdf_bytes*.

        Strategy
        --------
        1. Try PyMuPDF (fitz) for text extraction and table detection.
           - If fitz is not installed, fall through to pdfplumber for everything.
           - If fitz raises on open, raise ``InvalidFileError``.
        2. If PyMuPDF produces no tables, fall back to pdfplumber for table
           extraction only.
        3. If table extraction fails entirely but text succeeded, set
           ``table_extraction_warning`` and continue — do NOT raise.
        4. After text extraction, if ``len(raw_text.strip()) < 100`` raise
           ``InvalidFileError`` (scanned / image-only PDF).

        Returns
        -------
        PDFExtractionResult
            raw_text, tables (list[list[list[str]]]), table_extraction_warning
        """
        raw_text: str = ""
        tables: list[list[list[str]]] = []
        table_extraction_warning: str | None = None

        fitz_available = False
        try:
            import fitz  # PyMuPDF
            fitz_available = True
        except ImportError:
            logger.warning("PyMuPDF (fitz) is not installed; falling back to pdfplumber for all extraction.")

        if fitz_available:
            raw_text, tables, table_extraction_warning = self._extract_with_fitz(pdf_bytes)
        else:
            # fitz not available — use pdfplumber for both text and tables
            raw_text, tables, table_extraction_warning = self._extract_with_pdfplumber(pdf_bytes)

        # Requirement 2.4: insufficient text → InvalidFileError
        if len(raw_text.strip()) < 100:
            raise InvalidFileError(
                "PDF contains insufficient text (fewer than 100 characters). "
                "It may be a scanned image-only PDF."
            )

        return PDFExtractionResult(
            raw_text=raw_text,
            tables=tables,
            table_extraction_warning=table_extraction_warning,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_with_fitz(
        self, pdf_bytes: bytes
    ) -> tuple[str, list[list[list[str]]], str | None]:
        """Use PyMuPDF to extract text and (optionally) tables.

        Returns (raw_text, tables, table_extraction_warning).
        Raises InvalidFileError if the PDF cannot be opened.
        """
        import fitz  # noqa: PLC0415 — already confirmed available

        # Requirement 2.3: corrupt / unreadable file
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise InvalidFileError(f"Cannot open PDF: corrupt or unreadable file") from exc

        # Requirement 2.1: extract text from all pages
        page_texts: list[str] = []
        for page in doc:
            page_texts.append(page.get_text())
        raw_text = "\n".join(page_texts)

        # Requirement 2.2: attempt table extraction via PyMuPDF
        fitz_tables: list[list[list[str]]] = []
        table_extraction_warning: str | None = None

        try:
            for page in doc:
                if hasattr(page, "find_tables"):
                    tab_finder = page.find_tables()
                    for tab in tab_finder.tables:
                        # tab.extract() returns list[list[str | None]]
                        rows = [
                            [str(cell) if cell is not None else "" for cell in row]
                            for row in tab.extract()
                        ]
                        if rows:
                            fitz_tables.append(rows)
        except Exception as exc:
            logger.warning("PyMuPDF table extraction failed: %s", exc)
            table_extraction_warning = f"Table extraction failed: {exc}"

        doc.close()

        # Requirement 2.7: fall back to pdfplumber if no tables found
        if not fitz_tables and table_extraction_warning is None:
            logger.debug("PyMuPDF found no tables; trying pdfplumber fallback.")
            _, pdfplumber_tables, pdfplumber_warning = self._extract_tables_with_pdfplumber(pdf_bytes)
            return raw_text, pdfplumber_tables, pdfplumber_warning

        return raw_text, fitz_tables, table_extraction_warning

    def _extract_with_pdfplumber(
        self, pdf_bytes: bytes
    ) -> tuple[str, list[list[list[str]]], str | None]:
        """Use pdfplumber for both text and table extraction.

        Used when fitz is not installed.
        Raises InvalidFileError if the PDF cannot be opened.
        """
        try:
            import pdfplumber  # noqa: PLC0415
        except ImportError as exc:
            raise InvalidFileError(
                "Cannot open PDF: neither PyMuPDF nor pdfplumber is installed."
            ) from exc

        try:
            pdf_file = pdfplumber.open(io.BytesIO(pdf_bytes))
        except Exception as exc:
            raise InvalidFileError(f"Cannot open PDF: corrupt or unreadable file") from exc

        page_texts: list[str] = []
        tables: list[list[list[str]]] = []
        table_extraction_warning: str | None = None

        try:
            for page in pdf_file.pages:
                text = page.extract_text() or ""
                page_texts.append(text)

            try:
                for page in pdf_file.pages:
                    page_tables = page.extract_tables() or []
                    for raw_table in page_tables:
                        rows = [
                            [str(cell) if cell is not None else "" for cell in row]
                            for row in raw_table
                        ]
                        if rows:
                            tables.append(rows)
            except Exception as exc:
                logger.warning("pdfplumber table extraction failed: %s", exc)
                table_extraction_warning = f"Table extraction failed: {exc}"
        finally:
            pdf_file.close()

        raw_text = "\n".join(page_texts)
        return raw_text, tables, table_extraction_warning

    def _extract_tables_with_pdfplumber(
        self, pdf_bytes: bytes
    ) -> tuple[str, list[list[list[str]]], str | None]:
        """Extract tables only via pdfplumber (text already obtained from fitz).

        Returns ("", tables, warning).
        """
        try:
            import pdfplumber  # noqa: PLC0415
        except ImportError:
            return "", [], "Table extraction failed: pdfplumber is not installed"

        tables: list[list[list[str]]] = []
        table_extraction_warning: str | None = None

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf_file:
                for page in pdf_file.pages:
                    page_tables = page.extract_tables() or []
                    for raw_table in page_tables:
                        rows = [
                            [str(cell) if cell is not None else "" for cell in row]
                            for row in raw_table
                        ]
                        if rows:
                            tables.append(rows)
        except Exception as exc:
            logger.warning("pdfplumber table extraction failed: %s", exc)
            table_extraction_warning = f"Table extraction failed: {exc}"

        return "", tables, table_extraction_warning
