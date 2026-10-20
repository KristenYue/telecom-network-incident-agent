from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_plan_records_ci_compose_evidence_without_claiming_local_or_production_proof():
    plan = (ROOT / "docs" / "PLAN_COMPLETENESS.md").read_text(encoding="utf-8")
    assert "Linux CI 运行验收通过" in plan
    assert "compose-smoke" in plan
    assert "本机仍无 Docker" in plan
    assert "不证明真实运营商接入、性能压测、灾备或生产 SLO" in plan
    assert "双 Worker PostgreSQL" in plan
