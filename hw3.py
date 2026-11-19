#!/usr/bin/env python3
"""FTEC5660 HW3 student starter: an agent that applies 3 of Fisher's 15 points using tools."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sqlite3
import threading
import zlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


# by student
import re
import statistics


MODEL_NAME = "deepseek-v4-flash"
INTERVIEW_LIMIT = 10
MAX_SQL_ROWS = 50

# Philip Fisher, "Common Stocks and Uncommon Profits", Part One, Chapter 3.
# For every point, PASS means the company looks good on it. You choose 3
# points and decide yourself what PASS means for each of them.
FISHER_POINTS = {
    1: "Does the company have products or services with sufficient market potential to make possible a sizable increase in sales for at least several years?",
    2: "Does the management have a determination to continue to develop products or processes that will still further increase total sales potentials when the growth potentials of currently attractive product lines have largely been exploited?",
    3: "How effective are the company's research and development efforts in relation to its size?",
    4: "Does the company have an above-average sales organization?",
    5: "Does the company have a worthwhile profit margin?",
    6: "What is the company doing to maintain or improve profit margins?",
    7: "Does the company have outstanding labor and personnel relations?",
    8: "Does the company have outstanding executive relations?",
    9: "Does the company have depth to its management?",
    10: "How good are the company's cost analysis and accounting controls?",
    11: "Are there other aspects of the business, somewhat peculiar to the industry involved, which will give the investor important clues as to how outstanding the company may be in relation to its competition?",
    12: "Does the company have a short-range or long-range outlook in regard to profits?",
    13: "In the foreseeable future will the growth of the company require sufficient equity financing so that the larger number of shares then outstanding will largely cancel the existing stockholders' benefit from this anticipated growth?",
    14: "Does the management talk freely to investors about its affairs when things are going well but 'clam up' when troubles and disappointments occur?",
    15: "Does the company have a management of unquestionable integrity?",
}
VERDICTS = ("PASS", "FAIL")


class CompanyAssessment(BaseModel):
    q7_assessment: Literal["POSITIVE", "NEGATIVE", "UNCLEAR"] = Field(
        description="Overall assessment of labor and personnel relations."
    )
    q7_evidence: str = Field(description="Brief evidence for point 7.")
    q14_assessment: Literal["PASS", "FAIL", "UNCLEAR"] = Field(
        description="Assessment of management disclosure about detected trouble."
    )
    q14_evidence: str = Field(description="Brief evidence for point 14.")
    summary: str = Field(description="Two or three concise evidence-based sentences.")


def load_env_file(path: Path = Path(".env")) -> None:
    """Load the simple KEY=VALUE entries used by this homework."""
    if not path.is_file():
        return
    import os

    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        content = raw.decode("utf-32")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        content = raw.decode("utf-16")
    else:
        content = raw.decode("utf-8-sig")

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


# Choose any 3 of the 15 points, e.g. CHOSEN_POINTS = [1, 7, 15]. Your agent
# gives a PASS or FAIL verdict on these 3 points only, with your own rule for each.
CHOSEN_POINTS: list[int] = [5,7,14]  ### YOUR CODE HERE
"""
5: "Does the company have a worthwhile profit margin?"              
    > market 60% quantile or find out the margin
7: "Does the company have outstanding labor and personnel relations?"
    
14: "Does the management talk freely to investors about its affairs when things are going well but 'clam up' when troubles and disappointments occur?"

"""


### by students: help functons 
def _tool_map(tools: list[Any]) -> dict[str, Any]:
    """Map name to LangChain tool that could be accessed by agent"""
    return {tool.name: tool for tool in tools}


def _call_tool(tools: dict[str, Any], tool_name: str, **kwargs: Any) -> str:
    """Obtain companies proof from LangChain tool"""
    return str(tools[tool_name].invoke(kwargs))


async def _call_tool_async(
    tools: dict[str, Any], tool_name: str, **kwargs: Any
) -> str:
    """Use asyncio tool in the thread, avoid blocking asyncio。"""
    return await asyncio.to_thread(_call_tool, tools, tool_name, **kwargs)


def _parse_sql_table(raw: str) -> list[dict[str, str]]:
    """Analyze sql_query's return of 'column | column' text。"""
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.startswith("...")
    ]

    if len(lines) < 2 or lines[1] == "(no rows)":
        return []

    headers = [x.strip() for x in lines[0].split("|")]
    rows = []

    for line in lines[1:]:
        values = [x.strip() for x in line.split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))

    return rows


def _number(value: Any) -> float:
    """turn SQL return into numeric results"""
    text = str(value).strip().replace(",", "")
    return float(text)


def _quarter_from_month(month: str) -> str:
    year = month[:4]
    month_number = int(month[5:7])
    quarter = (month_number - 1) // 3 + 1
    return f"{year}Q{quarter}"


def _q5_evidence(sql: dict[str, Any]) -> dict[str, Any]:
    """
    Question 5:
    current profit rate >= median of industries profit rate -> pass
    """
    revenue_rows = _parse_sql_table(
        _call_tool(
            sql,
            "sql_query",
            query="""
                SELECT SUM(amount) AS revenue_2025
                FROM orders
                WHERE order_date >= '2025-01-01'
                  AND order_date < '2026-01-01'
            """,
        )
    )

    cost_rows = _parse_sql_table(
        _call_tool(
            sql,
            "sql_query",
            query="""
                SELECT
                    SUM(cost_of_sales) AS cost_of_sales,
                    SUM(selling_admin) AS selling_admin,
                    SUM(research_development) AS research_development
                FROM monthly_costs
                WHERE month >= '2025-01'
                  AND month <= '2025-12'
            """,
        )
    )

    industry_rows = _parse_sql_table(
        _call_tool(
            sql,
            "sql_query",
            query="""
                SELECT im.operating_margin_pct AS industry_margin_pct
                FROM company AS c
                JOIN industry_medians AS im
                  ON c.industry = im.industry
            """,
        )
    )

    if not revenue_rows or not cost_rows or not industry_rows:
        return {
            "assessment": "UNCLEAR",
            "evidence": "Required FY2025 or industry data was unavailable.",
        }

    revenue = _number(revenue_rows[0]["revenue_2025"])

    if revenue == 0:
        return {
            "assessment": "UNCLEAR",
            "evidence": "FY2025 revenue was zero, so operating margin could not be calculated.",
        }

    cost_of_sales = _number(cost_rows[0]["cost_of_sales"])
    selling_admin = _number(cost_rows[0]["selling_admin"])
    research_development = _number(cost_rows[0]["research_development"])
    industry_margin = _number(industry_rows[0]["industry_margin_pct"])

    operating_profit = (
        revenue
        - cost_of_sales
        - selling_admin
        - research_development
    )
    operating_margin = operating_profit / revenue * 100

    assessment = (
        "PASS"
        if operating_margin >= industry_margin
        else "FAIL"
    )

    return {
        "revenue_2025": revenue,
        "operating_profit_2025": operating_profit,
        "operating_margin_pct": operating_margin,
        "industry_margin_pct": industry_margin,
        "assessment": assessment,
        "evidence": (
            f"FY2025 operating margin was {operating_margin:.2f}%, "
            f"compared with the industry median of {industry_margin:.2f}%."
        ),
    }


async def _q7_evidence(tools: dict[str, Any]) -> dict[str, Any]:
    """
    Question 7:
    current_employee first, ask former_employee if unavailable.
    """

    answers = []

    current_answer = await _call_tool_async(
        tools,
        "interview",
        role="current_employee",
        topic="working_conditions",
    )
    answers.append(("current_employee", current_answer))

    cannot_comment = re.search(
        r"cannot comment|can't comment|unable to comment|"
        r"do not know|don't know|no comment|not able to comment",
        current_answer,
        flags=re.I,
    )

    if cannot_comment:
        former_answer = await _call_tool_async(
            tools,
            "interview",
            role="former_employee",
            topic="working_conditions",
        )
        answers.append(("former_employee", former_answer))

    return {
        "interviews": [
            {
                "role": role,
                "answer": answer,
            }
            for role, answer in answers
        ]
    }


def _q14_evidence(
    sql: dict[str, Any],
    earnings_call_quarters: set[str],
) -> dict[str, Any]:
    """
    Question 14:
    Check difficulties from the database. Agent compares the earnings call later.
    """

    cash_rows = _parse_sql_table(
        _call_tool(
            sql,
            "sql_query",
            query="""
                SELECT quarter, operating_cash_flow, cash_end
                FROM quarterly_cash
                ORDER BY quarter
            """,
        )
    )

    revenue_rows = _parse_sql_table(
        _call_tool(
            sql,
            "sql_query",
            query="""
                SELECT
                    substr(order_date, 1, 4) || 'Q' ||
                    (((CAST(substr(order_date, 6, 2) AS INTEGER) - 1) / 3) + 1)
                    AS quarter,
                    SUM(amount) AS revenue
                FROM orders
                GROUP BY quarter
                ORDER BY quarter
            """,
        )
    )

    return_rows = _parse_sql_table(
        _call_tool(
            sql,
            "sql_query",
            query="""
                SELECT
                    substr(month, 1, 4) || 'Q' ||
                    (((CAST(substr(month, 6, 2) AS INTEGER) - 1) / 3) + 1)
                    AS quarter,
                    SUM(units_shipped) AS units_shipped,
                    SUM(units_returned) AS units_returned
                FROM returns
                GROUP BY quarter
                ORDER BY quarter
            """,
        )
    )

    cash_by_quarter = {
        row["quarter"]: row
        for row in cash_rows
        if "quarter" in row
    }

    revenue_by_quarter = {
        row["quarter"]: _number(row["revenue"])
        for row in revenue_rows
        if "quarter" in row and row.get("revenue") not in (None, "")
    }

    returns_by_quarter = {}

    for row in return_rows:
        shipped = _number(row["units_shipped"])
        returned = _number(row["units_returned"])

        if shipped > 0:
            returns_by_quarter[row["quarter"]] = returned / shipped

    quarters = sorted(
        set(cash_by_quarter)
        & set(revenue_by_quarter)
        & set(returns_by_quarter)
    )

    evaluated_quarters = {}
    ocf_below_baseline = set()

    for index, current_quarter in enumerate(quarters):
        if current_quarter not in earnings_call_quarters:
            continue

        history_quarters = quarters[max(0, index - 5) : index]

        current_cash = cash_by_quarter[current_quarter]
        current_ocf = _number(current_cash["operating_cash_flow"])
        current_revenue = revenue_by_quarter[current_quarter]

        current_ocf_margin = (
            current_ocf / current_revenue
            if current_revenue
            else None
        )
        ocf_mean = None

        history_ocf_margins = []

        for quarter in history_quarters:
            revenue = revenue_by_quarter[quarter]
            ocf = _number(cash_by_quarter[quarter]["operating_cash_flow"])

            if revenue:
                history_ocf_margins.append(ocf / revenue)

        history_return_rates = [
            returns_by_quarter[quarter]
            for quarter in history_quarters
        ]

        reasons = []

        if current_ocf < 0:
            reasons.append("operating_cash_flow_negative")

        if current_ocf_margin is not None and len(history_ocf_margins) == 5:
            ocf_mean = statistics.mean(history_ocf_margins)
            if ocf_mean - current_ocf_margin >= 0.02:
                ocf_below_baseline.add(current_quarter)

        if len(history_return_rates) == 5:
            return_mean = statistics.mean(history_return_rates)
            return_std = statistics.pstdev(history_return_rates)
            current_return_rate = returns_by_quarter[current_quarter]

            if (
                current_return_rate > return_mean + 2 * return_std
                and current_return_rate - return_mean >= 0.01
            ):
                reasons.append("return_rate_anomalously_high")

        evaluated_quarters[current_quarter] = {
            "quarter": current_quarter,
            "reasons": reasons,
            "operating_cash_flow": current_ocf,
            "operating_cash_flow_margin": current_ocf_margin,
            "ocf_margin_baseline_mean": ocf_mean,
            "return_rate": returns_by_quarter[current_quarter],
        }

    report_quarters = [
        quarter for quarter in quarters if quarter in earnings_call_quarters
    ]
    quarter_indexes = {quarter: index for index, quarter in enumerate(quarters)}

    for previous, current in zip(report_quarters, report_quarters[1:]):
        consecutive = quarter_indexes[current] == quarter_indexes[previous] + 1
        if (
            consecutive
            and previous in ocf_below_baseline
            and current in ocf_below_baseline
        ):
            evaluated_quarters[previous]["reasons"].append(
                "ocf_margin_below_baseline_consecutive"
            )
            evaluated_quarters[current]["reasons"].append(
                "ocf_margin_below_baseline_consecutive"
            )

    trouble = [
        item for item in evaluated_quarters.values() if item["reasons"]
    ]

    return {
        "earnings_call_quarters": sorted(earnings_call_quarters),
        "trouble_found": bool(trouble),
        "trouble_quarters": trouble,
    }


def _print_company_trace(
    company_name: str,
    q5: dict[str, Any],
    q7: dict[str, Any],
    q14: dict[str, Any],
    q14_documents: str,
    points: dict[int, str],
    model_result: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    """Print the evidence behind each company's point verdicts."""
    print(f"\n[{company_name}]")
    print(f"  Q5 {points.get(5, 'FAIL')}: {q5.get('evidence', 'No margin evidence')}")

    interviews = q7.get("interviews", [])
    if interviews:
        for item in interviews:
            print(f"  Q7 interview ({item['role']}): {item['answer']}")
    else:
        print("  Q7 interview: unavailable")

    if model_result:
        print(
            f"  Q7 {points.get(7, 'FAIL')}: "
            f"{model_result.get('q7_evidence', 'No model evidence')}"
        )

    trouble = q14.get("trouble_quarters", [])
    if "trouble_found" not in q14:
        print("  Q14 evidence: unavailable")
    elif trouble:
        for item in trouble:
            print(
                f"  Q14 detected {item['quarter']} "
                f"({', '.join(item['reasons'])}): "
                f"OCF={item['operating_cash_flow']:.2f}, "
                f"OCF margin={item['operating_cash_flow_margin']}, "
                f"return rate={item['return_rate']:.4%}"
            )
        if q14_documents:
            print("  Q14 matching earnings-call evidence:")
            print(q14_documents.strip())
    else:
        print("  Q14: no predefined material difficulty in covered quarters")

    if model_result:
        print(
            f"  Q14 {points.get(14, 'FAIL')}: "
            f"{model_result.get('q14_evidence', 'No model evidence')}"
        )
    elif error is not None:
        print(f"  Model analysis error: {type(error).__name__}: {str(error).splitlines()[0]}")

    print(
        "  Final: "
        + ", ".join(f"Q{point}={points.get(point, 'FAIL')}" for point in (5, 7, 14))
    )
###



def build_agent() -> Any:
    """Create the DeepSeek model once for the whole run."""
    import os
    from langchain_deepseek import ChatDeepSeek

    api_key = os.environ.get("DEEPSEEK_API_KEY")

    if not api_key or api_key == "your_key_here":
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not configured. "
            "Set it in the local .env file."
        )

    system_prompt = """
You are an evidence-based Fisher investment analyst.

The selected Fisher points are 5, 7, and 14.

Point 5:
Use the supplied FY2025 operating-margin calculation. PASS when the
company operating margin is greater than or equal to the industry median.
Do not recalculate numbers mentally.

Point 7:
Read the supplied employee interview. Return POSITIVE when it clearly
supports outstanding labor and personnel relations, NEGATIVE when it
clearly describes serious problems, and UNCLEAR when it cannot establish
either conclusion. Do not count positive or negative keywords.

Point 14:
The supplied database evidence checks only quarters with a matching supplied
earnings call for predefined financial or return-rate difficulties. Earlier
quarters are used only to calculate the five-quarter baseline; never treat an
anomaly in those baseline quarters as an undisclosed difficulty. Read the
matching earnings-call text for each detected difficulty.
Treat negative operating cash flow as a material difficulty. A positive but
weaker operating-cash-flow margin is material only when it is at least two
percentage points below its own prior-five-quarter mean in two consecutive
quarters that have earnings calls. Do not fail the company for one isolated
positive-cash-flow decline.
PASS when management clearly acknowledges and addresses the detected
difficulty. FAIL when the data shows a difficulty but management omits,
evades, or materially contradicts it. If no predefined difficulty was
detected, return PASS.

Fill every field in the required structured response. Use only the listed
assessment values. Keep evidence concise and tie every claim to supplied data.
Return the result as a valid JSON object matching the required schema.

Do not invent facts. Use only the supplied evidence.
""".strip()

    model = ChatDeepSeek(
        model=MODEL_NAME,
        api_key=api_key,
        extra_body={"thinking": {"type": "disabled"}},
    )
    structured_model = model.with_structured_output(
        CompanyAssessment,
        method="function_calling",
    )

    return {
        "model": structured_model,
        "system_prompt": system_prompt,
    }


async def analyze_companies(
    agent: Any,
    companies: dict[str, list[Any]],
) -> dict[str, dict[str, Any]]:
    """Analyze every company using its own four tools."""

    results: dict[str, dict[str, Any]] = {}

    for company_name, company_tools in companies.items():
        q5_verdict = "FAIL"
        q7_verdict = "FAIL"
        q14_verdict = "FAIL"
        q5: dict[str, Any] = {}
        q7: dict[str, Any] = {}
        q14: dict[str, Any] = {}
        q14_documents = ""
        model_result: dict[str, Any] | None = None
        try:
            tools = _tool_map(company_tools)

            # Q5：only use database data
            q5 = await asyncio.to_thread(_q5_evidence, tools)
            if q5.get("assessment") in VERDICTS:
                q5_verdict = q5["assessment"]

            # Q7: from employees interview
            q7 = await _q7_evidence(tools)

            # Only score difficulties from quarters with a supplied earnings call.
            document_listing = await _call_tool_async(
                tools,
                "list_documents",
            )
            earnings_files = re.findall(
                r"earnings_call_(\d{4}q\d+)\.md",
                document_listing,
                flags=re.I,
            )
            earnings_call_quarters = {quarter.upper() for quarter in earnings_files}

            # Earlier quarters remain available as the five-quarter baseline.
            q14 = await asyncio.to_thread(
                _q14_evidence,
                tools,
                earnings_call_quarters,
            )
            if not q14["trouble_found"]:
                q14_verdict = "PASS"

            if q14["trouble_found"]:
                relevant_quarters = {
                    item["quarter"]
                    for item in q14["trouble_quarters"]
                }

                for filename in re.findall(
                    r"earnings_call_\d{4}q\d+\.md",
                    document_listing,
                    flags=re.I,
                ):
                    match = re.search(
                        r"earnings_call_(\d{4}q\d+)\.md",
                        filename,
                        flags=re.I,
                    )

                    if match and match.group(1).upper() in relevant_quarters:
                        q14_documents += await _call_tool_async(
                            tools,
                            "read_document",
                            name=filename,
                        )
                        q14_documents += "\n\n"

            evidence = {
                "company": company_name,
                "q5": q5,
                "q7": q7,
                "q14_database": q14,
                "q14_earnings_calls": q14_documents,
            }

            response = await agent["model"].ainvoke(
                [
                    ("system", agent["system_prompt"]),
                    (
                        "human",
                        "Analyze this company using only the evidence below. "
                        "Return a valid JSON object and complete every field in "
                        "the required response.\n\n"
                        + json.dumps(
                            evidence,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    ),
                ]
            )

            model_result = response
            if isinstance(model_result, BaseModel):
                model_result = model_result.model_dump()
            if not isinstance(model_result, dict):
                raise ValueError("Agent response did not contain structured_response")

            q7_assessment = model_result["q7_assessment"]
            q14_assessment = model_result["q14_assessment"]

            q7_verdict = {
                "POSITIVE": "PASS",
                "NEGATIVE": "FAIL",
                "UNCLEAR": "FAIL",
            }.get(q7_assessment, "FAIL")

            if q14_assessment in VERDICTS:
                q14_verdict = q14_assessment

            results[company_name] = {
                "points": {
                    5: q5_verdict,
                    7: q7_verdict,
                    14: q14_verdict,
                },
                "summary": model_result["summary"].strip(),
            }
            # _print_company_trace(
            #     company_name,
            #     q5,
            #     q7,
            #     q14,
            #     q14_documents,
            #     results[company_name]["points"],
            #     model_result=model_result,
            # )

        except Exception as exc:
            results[company_name] = {
                "points": {5: q5_verdict, 7: q7_verdict, 14: q14_verdict},
                "summary": (
                    f"Structured analysis failed: {type(exc).__name__}: {exc}. "
                    "Unresolved points use conservative FAIL defaults."
                ),
            }
            # _print_company_trace(
            #     company_name,
            #     q5,
            #     q7,
            #     q14,
            #     q14_documents,
            #     results[company_name]["points"],
            #     model_result=model_result,
            #     error=exc,
            # )

    return results


# Everything below is provided runner/scoring code. No edits are needed.
# Your code must read company data only through these tools: do not open
# company.db or interviews.dat directly.

INTERVIEWS_USED: dict[str, int] = {}


def company_folders(folder: Path) -> list[Path]:
    """Return one sub-folder per company directly inside *folder*, sorted by name."""
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))


def make_tools(company_folder: Path) -> list[Any]:
    """Build the four tools for one company."""
    from langchain_core.tools import tool

    name = company_folder.name
    db_uri = f"{(company_folder / 'company.db').resolve().as_uri()}?mode=ro"
    answers = json.loads(zlib.decompress((company_folder / "interviews.dat").read_bytes()))
    documents = {p.name: p for p in sorted(company_folder.glob("*.md"))}
    lock = threading.Lock()
    INTERVIEWS_USED[name] = 0

    @tool
    def list_documents() -> str:
        """List this company's documents (annual letter, earnings calls, news) with their dates."""
        lines = []
        for doc_name, path in documents.items():
            text = path.read_text(encoding="utf-8").splitlines()
            dated = next((line for line in text if line.startswith("Date:")), "")
            lines.append(f"{doc_name}: {text[0].lstrip('# ')} ({dated or 'undated'})")
        return "\n".join(lines)

    @tool
    def read_document(name: str) -> str:
        """Return the full text of one document named by list_documents, e.g. 'annual_letter_2025.md'."""
        path = documents.get(name.strip())
        if path is None:
            return f"No document named {name!r}. Available: {', '.join(documents)}"
        return path.read_text(encoding="utf-8")

    @tool
    def sql_query(query: str) -> str:
        """Run one read-only SQLite query on this company's database and return at most 50 rows.

        Amounts are in USD thousands. Dates are 'YYYY-MM-DD', months 'YYYY-MM', quarters like '2025Q3'.
        Tables:
          company(name, industry)
          industry_medians(industry, revenue_growth_2y_pct, new_product_share_pct, new_product_sales_per_rd, operating_margin_pct)
          orders(order_id, order_date, product, customer, amount, note)
          products(product, launch_date)
          monthly_costs(month, cost_of_sales, selling_admin, research_development)
          quarterly_cash(quarter, operating_cash_flow, capex, cash_end)
          capex_plan(year, planned_capex)
          returns(month, units_shipped, units_returned)
          insider_trades(trade_date, person, title, side, shares, price)
        Use SUM, GROUP BY and WHERE to compute totals rather than reading raw rows.
        """
        try:
            con = sqlite3.connect(db_uri, uri=True)
            try:
                cursor = con.execute(query)
                columns = [c[0] for c in cursor.description or []]
                rows = cursor.fetchmany(MAX_SQL_ROWS + 1)
            finally:
                con.close()
        except sqlite3.Error as exc:
            return f"SQL error: {exc}"
        if not columns:
            return "Query returned no columns."
        fmt = lambda v: f"{v:.2f}" if isinstance(v, float) else str(v)  # noqa: E731
        out = [" | ".join(columns)] + [" | ".join(fmt(v) for v in row) for row in rows[:MAX_SQL_ROWS]]
        if len(rows) > MAX_SQL_ROWS:
            out.append(f"... more rows not shown (limit {MAX_SQL_ROWS}); aggregate or add LIMIT/OFFSET.")
        if not rows:
            out.append("(no rows)")
        return "\n".join(out)

    @tool
    def interview(role: str, topic: str) -> str:
        """Interview one person about the company (at most 10 interviews per company).

        role: customer, current_employee, former_employee, competitor or supplier.
        topic: sales_team, working_conditions, top_management, decision_making or competitive_edge.
        People who would not know about a topic say so; the README lists who knows what.
        """
        role, topic = role.strip().lower(), topic.strip().lower()
        if role not in answers:
            return f"Unknown role {role!r}. Roles: {', '.join(answers)}. (Not counted.)"
        if topic not in answers[role]:
            return f"Unknown topic {topic!r}. Topics: {', '.join(answers[role])}. (Not counted.)"
        with lock:
            if INTERVIEWS_USED[name] >= INTERVIEW_LIMIT:
                return f"Interview limit reached: {INTERVIEW_LIMIT} interviews per company."
            INTERVIEWS_USED[name] += 1
        return answers[role][topic]

    return [list_documents, read_document, sql_query, interview]


def normalize_verdict(value: Any) -> str | None:
    """Accept PASS/FAIL (any case) or a boolean."""
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    text = str(getattr(value, "content", value)).strip().upper()
    return text if text in VERDICTS else None


def check_chosen_points(chosen: Any) -> list[int]:
    """CHOSEN_POINTS must name 3 different points between 1 and 15."""
    try:
        points = sorted({int(p) for p in chosen})
    except (TypeError, ValueError):
        points = []
    if len(points) != 3 or len(chosen) != 3 or not all(p in FISHER_POINTS for p in points):
        raise SystemExit("Set CHOSEN_POINTS at the top of hw3.py to 3 different point numbers "
                         f"between 1 and 15, e.g. [1, 7, 15] (now: {chosen!r}).")
    return points


def normalize_points(points: Any, chosen: list[int]) -> dict[int, str | None]:
    """Map each chosen point number to PASS/FAIL, or None when missing/invalid."""
    points = points if isinstance(points, dict) else {}
    by_number: dict[int, Any] = {}
    for key, value in points.items():
        try:
            by_number[int(key)] = value
        except (TypeError, ValueError):
            continue
    return {p: normalize_verdict(by_number.get(p)) for p in chosen}


def read_ground_truth(folder: Path) -> dict[str, dict[str, Any]]:
    """Read the expected 15 point verdicts per company."""
    path = folder / "ground_truth.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def point_errors(points: dict[int, str | None], expected: dict[str, Any] | None) -> tuple[int, str]:
    """Count correct point verdicts and describe the wrong ones."""
    if expected is None:
        return 0, ""
    wrong = []
    for p in points:
        truth = expected["points"][str(p)]
        if points[p] != truth:
            wrong.append(f"{p}: expected {truth}, predicted {points[p] or 'missing'}")
    if all(v is None for v in points.values()):
        return 0, "all point verdicts missing"
    return len(points) - len(wrong), "; ".join(wrong)


def balanced_point_accuracy(
    analyses: dict[str, Any], truth: dict[str, dict[str, Any]], names: list[str], chosen: list[int]
) -> float:
    """Mean of the accuracy on true-PASS points and on true-FAIL points.

    Most verdicts are PASS, so answering PASS everywhere gets a high plain
    accuracy but only 50% balanced accuracy. Grading uses the balanced number.
    """
    hits = {"PASS": [0, 0], "FAIL": [0, 0]}
    for name in names:
        if name not in truth:
            continue
        entry = analyses.get(name)
        points = normalize_points(entry.get("points") if isinstance(entry, dict) else None, chosen)
        for p in chosen:
            expected = truth[name]["points"][str(p)]
            hits[expected][0] += points[p] == expected
            hits[expected][1] += 1
    rates = [h / n for h, n in hits.values() if n]
    return sum(rates) / len(rates) if rates else 0.0


def write_results(
    names: list[str], analyses: dict[str, Any], truth: dict[str, dict[str, Any]], chosen: list[int]
) -> tuple[Path, int]:
    """Write results.csv and return the number of correct point verdicts."""
    output = Path("results.csv")
    correct_points = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company", "points", "points_correct", "point_errors", "interviews_used", "summary"])
        for name in names:
            entry = analyses.get(name)
            entry = entry if isinstance(entry, dict) else {}
            points = normalize_points(entry.get("points"), chosen)
            expected = truth.get(name)
            n_points, errors = point_errors(points, expected)
            correct_points += n_points
            writer.writerow([
                name,
                " ".join(f"{p}:{points[p] or 'missing'}" for p in chosen),
                f"{n_points}/{len(chosen)}" if expected else "",
                errors,
                INTERVIEWS_USED.get(name, 0),
                str(entry.get("summary", "")).strip(),
            ])
    return output, correct_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run FTEC5660 HW3 on company data folders")
    parser.add_argument(
        "--data-folder",
        required=True,
        type=Path,
        help="folder containing one sub-folder per company",
    )
    return parser.parse_args()


async def run(folder: Path) -> int:
    folders = company_folders(folder)
    if not folders:
        raise SystemExit(f"no company folders found in {folder}")

    chosen = check_chosen_points(CHOSEN_POINTS)
    load_env_file()
    companies = {path.name: make_tools(path) for path in folders}
    agent = build_agent()
    analyses = await analyze_companies(agent, companies)
    if not isinstance(analyses, dict):
        raise TypeError("analyze_companies() must return a dictionary")

    truth = read_ground_truth(folder)
    output, correct_points = write_results(list(companies), analyses, truth, chosen)
    summary = f" Your points: {', '.join(map(str, chosen))}."
    if truth:
        summary += (
            f" Point accuracy: {correct_points}/{len(companies) * len(chosen)}"
            f" (balanced: {balanced_point_accuracy(analyses, truth, list(companies), chosen):.1%})."
        )
    print(f"Processed {len(companies)} compan{'y' if len(companies) == 1 else 'ies'}. Wrote {output}.{summary}")
    return 0


def main() -> int:
    args = parse_args()
    if not args.data_folder.is_dir():
        raise SystemExit(f"not a folder: {args.data_folder}")
    return asyncio.run(run(args.data_folder))


if __name__ == "__main__":
    raise SystemExit(main())
