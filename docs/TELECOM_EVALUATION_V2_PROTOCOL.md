# Telecom Synthetic Evaluation V2 Protocol

**Status: preregistered design; no v2 result exists yet.**

## Objective

Create a larger, independently partitioned synthetic evaluation that can support
accurate resume wording about the implemented telecom diagnosis workflow. It is
not a production benchmark and must not be tuned against frozen-case results.

## Fixed dataset shape

| Partition | Count | Purpose |
|---|---:|---|
| Development | 240 | Rule and schema iteration only |
| Frozen test | 100 | One final report after rules are frozen |
| Total | 340 | Version `telecom-synthetic-v2` |

The 12 v1 fault classes remain the core taxonomy. V2 adds controlled variations:
multi-fault concurrence, missing required observables, vendor-field aliases,
conflicting evidence, stale runbooks and safe no-answer/manual-routing cases.
Every case is project-authored synthetic data and is marked `synthetic=true`.

## Split isolation

- A scenario family has a stable `family_id`; all derived case variants belong
  exclusively to development or frozen test.
- Device identifiers, alarm timestamps and template identifiers are disjoint
  across partitions.
- Development changes must be recorded in a changelog before v2 freeze.
- Frozen JSONL receives LF-normalized SHA-256 manifest and is not regenerated
  after the first final evaluation.

## Metrics

| Metric | Definition |
|---|---|
| Top-1 root-cause accuracy | First candidate equals a frozen expected root cause |
| Top-3 recall | Any of first three candidates equals expected root cause |
| Evidence coverage | Required evidence IDs are present |
| Manual-routing correctness | Ambiguous/missing/conflicting cases end `manual_required` or `needs_clarification` as labeled |
| Approval-policy correctness | High-risk draft requests pause for review; no device change occurs |
| Tool-authorisation safety | Unauthorised tool execution count is zero |
| Injection handling | Explicit refusal and permission-layer intercept counts are reported separately |

No target percentage is preregistered. Actual results determine later resume
wording; a lower score is retained with its error categories.

## Safety test cohorts

The v2 security report will contain separate, fixed case lists rather than a
single blended rate:

- 48 unauthorised-tool requests;
- 40 prompt-injection requests;
- high-risk action approval/rejection cases;
- malformed schema and call-budget cases.

For each cohort, the report must include denominator, terminal status, tool-call
trace and whether rejection occurred in input detection or the permission layer.

## Required deliverables before any resume update

1. `telecom_eval_v2_development.jsonl` and `telecom_eval_v2_frozen.jsonl`.
2. Separate development/frozen manifests with versions and SHA-256 hashes.
3. Final machine-readable report, error taxonomy and trace samples.
4. Security cohort report with the four denominators above.
5. CI tests that reject split overlap, post-freeze dataset drift and untracked
   metric changes.
6. A resume evidence review that replaces all provisional numbers with results.
