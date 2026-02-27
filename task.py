## task.py
from crewai import Task
from agents import financial_analyst_agent, verifier_agent, investment_advisor_agent, risk_assessor_agent

# ---------------------------------------------------------------------------
# KEY CHANGE: Tasks no longer call the PDF tool.
# The document text is pre-extracted in main.py and passed in as
# {document_content}. This means each agent gets the text immediately
# with ZERO tool calls, cutting token usage from 3x to 1x per pipeline run.
# ---------------------------------------------------------------------------

# BUG FIX #14 (Prompt): verification task used agent=financial_analyst instead
# of agent=verifier — the dedicated verification agent was never used.
# Also the description told it to "just guess" and "hallucinate financial terms".
# Fix: Assigned to verifier agent with a structured, honest verification checklist.

# BUG FIX #15 (Prompt): All task descriptions encouraged hallucination, made-up
# URLs, ignoring the user query, and contradicting itself in the same response.
# Fix: All tasks now use structured descriptions grounded in {document_content}.

def verification_task(verifier_agent):
    return Task(
        description=(
            "You have already been given the full document text below.\n"
            "DO NOT call any tools — the content is in {document_content}.\n\n"
            "DOCUMENT CONTENT:\n{document_content}\n\n"
            "Using only the text above:\n"
            "1. Identify the document type (annual report, quarterly update, etc.).\n"
            "2. Confirm presence of financial sections (income statement, balance sheet, "
            "cash flow, key metrics).\n"
            "3. Note the company name, reporting period, and currency.\n"
            "4. State VERIFIED or NOT A FINANCIAL DOCUMENT."
        ),
        expected_output=(
            "3-4 lines:\n"
            "- Document Type\n"
            "- Status: VERIFIED / NOT A FINANCIAL DOCUMENT\n"
            "- Sections found\n"
            "- Company, period, currency"
        ),
        agent=verifier_agent,
        async_execution=False,
    )

def analyze_financial_document_task(financial_analyst_agent):
    return Task(
        description=(
            "You have already been given the full document text below.\n"
            "DO NOT call any tools — the content is in {document_content}.\n\n"
            "DOCUMENT CONTENT:\n{document_content}\n\n"
            "Answer this query using only the text above: {query}\n\n"
            "Extract specific figures and trends relevant to the query. Be concise."
        ),
        expected_output=(
            "5 bullet points maximum:\n"
            "- Direct answer to the query with figures\n"
            "- Key metrics with values\n"
            "- Notable trends"
        ),
        agent=financial_analyst_agent,
        async_execution=False,
    )

def investment_task(investment_advisor_agent):
    return Task(
        description=(
            "You have already been given the full document text below.\n"
            "DO NOT call any tools — the content is in {document_content}.\n\n"
            "DOCUMENT CONTENT:\n{document_content}\n\n"
            "For query: {query}\n"
            "Identify financial health indicators and provide 3-5 investment observations "
            "grounded in the document. End with a disclaimer."
        ),
        expected_output=(
            "3-5 bullet points:\n"
            "- Investment observations with supporting figures\n"
            "- Disclaimer: Not personal financial advice"
        ),
        agent=investment_advisor_agent,
        async_execution=False,
    )

def risk_assessment_task(risk_assessor_agent):
    return Task(
        description=(
            "You have already been given the full document text below.\n"
            "DO NOT call any tools — the content is in {document_content}.\n\n"
            "DOCUMENT CONTENT:\n{document_content}\n\n"
            "For query: {query}\n"
            "List 3-5 key risks from the document. "
            "Rate each Low/Medium/High with one line of evidence."
        ),
        expected_output=(
            "3-5 risks:\n"
            "- Risk name | Severity | Evidence from document"
        ),
        agent=risk_assessor_agent,
        async_execution=False,
    )