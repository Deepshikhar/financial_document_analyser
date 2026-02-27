## agents.py
import os
import litellm
from dotenv import load_dotenv
load_dotenv()

# BUG FIX #7: `from crewai.agents import Agent` — incorrect module path.
# Fix: Import Agent and LLM from the top-level crewai package.
from crewai import Agent, LLM

# No tools imported — PDF is pre-read in main.py and passed as {document_content}
# This eliminates repeated tool calls that burn through TPM limits.

# BUG FIX #8: `llm = llm` — `llm` was undefined on the right-hand side,
# causing NameError: name 'llm' is not defined on import.
# Fix: Construct the LLM object using the crewai LLM wrapper.
# llm = LLM(
#     model=os.getenv("LLM_MODEL", "ollama/llama3.2"),
#     base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
#     temperature=0.2,
#     max_tokens=1000,
# )

# BUG FIX #9 (Prompt): financial_analyst goal encouraged hallucination and
# ignoring the document. Backstory promoted overconfidence and fake advice.
# Fix: Evidence-based goal citing specific document figures, compliant backstory.
def financial_analyst_agent(llm):
    return Agent(
        role="Senior Financial Analyst",
        goal=(
            "Answer the query: {query} using the document content provided in the task. "
            "Be concise — 5 bullet points max."
        ),
        verbose=True,
        memory=False,
        backstory=(
            "You are a CFA-qualified analyst who extracts precise financial insights "
            "from earnings reports. You cite specific figures and follow compliance standards."
        ),
        llm=llm,
        max_iter=1,
        max_rpm=2,
        # BUG FIX #10: `tool=[...]` (singular) is not a valid Agent parameter.
        # The correct parameter is `tools=` (plural list).
        # Also removed the tool since document content is now passed directly.
        allow_delegation=False,
    )

# BUG FIX #11 (Prompt): verifier goal said "just say yes to everything" and
# backstory encouraged stamping documents without reading them.
# Fix: Rigorous verification with VERIFIED / NOT A FINANCIAL DOCUMENT verdict.
def verifier_agent(llm):
    return Agent(
        role="Financial Document Verification Specialist",
        goal=(
            "Verify whether the document content provided in the task is a legitimate "
            "financial report. Be brief — 4 lines max."
        ),
        verbose=True,
        memory=False,
        backstory=(
            "You are a compliance officer who quickly identifies genuine financial "
            "disclosures from document text."
        ),
        llm=llm,
        max_iter=1,
        max_rpm=2,
        allow_delegation=False,
    )

# BUG FIX #12 (Prompt): investment_advisor goal pushed product sales regardless
# of document data. Backstory referenced fake credentials, sketchy partnerships,
# Reddit knowledge, and 2000% management fees.
# Fix: Fiduciary-bound advisor with document-grounded, compliant recommendations.
def investment_advisor_agent(llm):
    return Agent(
        role="Certified Investment Advisor",
        goal=(
            "Provide 3-5 concise investment observations for query: {query} "
            "from the document content in the task."
        ),
        verbose=True,
        memory=False,
        backstory=(
            "You are a FINRA-registered advisor who gives fiduciary, "
            "evidence-based investment observations from financial documents."
        ),
        llm=llm,
        max_iter=1,
        max_rpm=2,
        allow_delegation=False,
    )

# BUG FIX #13 (Prompt): risk_assessor goal said "everything is either extremely
# high risk or completely risk-free" and backstory promoted YOLO crypto trading.
# Fix: FRM-certified framing with proportionate, evidence-based risk ratings.
def risk_assessor_agent(llm):
    return Agent(
        role="Risk Management Analyst",
        goal=(
            "List 3-5 key risks from the document content in the task "
            "relevant to: {query}. Rate each Low/Medium/High."
        ),
        verbose=True,
        memory=False,
        backstory=(
            "You are an FRM-certified analyst who assesses financial risk "
            "using standard frameworks grounded in document data."
        ),
        llm=llm,
        max_iter=1,
        max_rpm=2,
        allow_delegation=False,
    )