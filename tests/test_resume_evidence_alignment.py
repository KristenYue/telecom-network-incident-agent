from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resume_alignment_preserves_v1_boundary_and_v2_is_not_a_result() -> None:
    alignment = (ROOT / "docs" / "RESUME_EVIDENCE_ALIGNMENT.md").read_text(
        encoding="utf-8"
    )
    protocol = (ROOT / "docs" / "TELECOM_EVALUATION_V2_PROTOCOL.md").read_text(
        encoding="utf-8"
    )

    assert "telecom-synthetic-v1" in alignment
    assert "83%" in alignment
    assert "94%" in alignment
    assert "v2" in alignment
    assert "240" in protocol
    assert "100" in protocol
    assert "48 unauthorised-tool requests" in protocol
    assert "40 prompt-injection requests" in protocol
    assert "No target percentage is preregistered" in protocol
    assert "no v2 result exists yet" in protocol
