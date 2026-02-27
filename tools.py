## tools.py
import os
import re
from dotenv import load_dotenv
load_dotenv()

# BUG FIX #1: `from crewai_tools import tools` — `tools` is not a valid export
# from crewai_tools, causing ImportError on import.
# Fix: Import only SerperDevTool using its full module path.
from crewai_tools.tools.serper_dev_tool.serper_dev_tool import SerperDevTool

# BUG FIX #2: `Pdf` was never imported anywhere — using it caused NameError.
# Fix: Use pypdf.PdfReader which is a real, installable library.
from pypdf import PdfReader

# BUG FIX #3: Missing @tool decorator import — crewai agents cannot discover
# or invoke functions that aren't decorated with @tool.
from crewai.tools import tool

## Creating search tool
search_tool = SerperDevTool()

# Word limit for document truncation (fits within Ollama/Groq token limits)
MAX_WORDS = 6000


def _clean_and_truncate(text: str, max_words: int = MAX_WORDS) -> str:
    """Remove excess whitespace and truncate to max_words."""
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = ' '.join(words[:max_words])
    return (
        truncated
        + f"\n\n[Document truncated to {max_words} words. "
        f"Full document ~{len(words)} words.]"
    )


class FinancialDocumentTool():

    # BUG FIX #4: `async def read_data_tool(...)` — CrewAI tool functions must
    # be synchronous. Async functions are not supported as CrewAI tools.
    # Fix: Removed `async` keyword.

    # BUG FIX #5: Missing `self` parameter and no decorators — calling class
    # methods without `self` raises TypeError. Fix: Added @staticmethod + @tool.

    # BUG FIX #6: Missing @tool decorator — agents cannot discover or invoke
    # undecorated functions. Fix: Added @tool("...") decorator.

    @staticmethod
    @tool("Read Financial PDF Document")
    def read_data_tool(path: str = 'data/sample.pdf') -> str:
        """Tool to read and extract text content from a PDF financial document.

        Args:
            path (str): Path to the PDF file. Defaults to 'data/sample.pdf'.

        Returns:
            str: Extracted text from the document, truncated to fit token limits.
        """
        try:
            reader = PdfReader(path)
        except FileNotFoundError:
            return f"ERROR: File not found at '{path}'."
        except Exception as e:
            return f"ERROR: Could not read PDF: {str(e)}"

        full_report = ""
        for page in reader.pages:
            content = page.extract_text()
            if content:
                full_report += content + "\n"

        if not full_report.strip():
            return "ERROR: No text could be extracted (may be image-based)."

        return _clean_and_truncate(full_report)


class InvestmentTool:

    @staticmethod
    @tool("Analyze Investment Data")
    def analyze_investment_tool(financial_document_data: str) -> str:
        """Analyze extracted financial document data for investment insights.

        Args:
            financial_document_data (str): Raw text from a financial document.

        Returns:
            str: Cleaned financial data ready for investment analysis.
        """
        processed_data = re.sub(r'[ \t]{2,}', ' ', financial_document_data)
        return processed_data


class RiskTool:

    @staticmethod
    @tool("Create Risk Assessment")
    def create_risk_assessment_tool(financial_document_data: str) -> str:
        """Perform a risk assessment based on financial document data.

        Args:
            financial_document_data (str): Raw text from a financial document.

        Returns:
            str: Confirmation that data was received for risk analysis.
        """
        return f"Risk assessment input received ({len(financial_document_data)} chars)."