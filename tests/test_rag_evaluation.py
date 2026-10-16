from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.rag_evaluation import evaluate_rag


def test_synthetic_rag_contract_gate():
    report = run_non_yielding(evaluate_rag())
    assert report["query_count"] == 19
    assert all(value == 1.0 for value in report["metrics"].values())
