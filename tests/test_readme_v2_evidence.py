from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_v2_evidence_to_its_synthetic_boundary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "telecom-synthetic-v2" in readme
    assert "240 条 development 输入" in readme
    assert "100 条" in readme
    assert "不是**身份认证或 RBAC" in readme
    assert "不要把这些合成离线结果表述为运营商" in readme
    assert "INTERVIEW_EVIDENCE_CARD.md" in readme
