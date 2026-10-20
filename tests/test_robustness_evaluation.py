from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.diagnosis import canonical_alarm_type
from telecom_incident_agent.robustness_evaluation import evaluate_robustness


def test_only_documented_vendor_aliases_are_normalized():
    assert canonical_alarm_type("VENDORX_RX_LOW") == "rx_power_low"
    assert canonical_alarm_type("unknown_vendor_alarm") == "unknown_vendor_alarm"


def test_challenge_suite_handles_aliases_boundaries_and_multi_faults():
    report = run_non_yielding(evaluate_robustness())
    assert report["case_count"] == 4
    assert report["passed"] is True
