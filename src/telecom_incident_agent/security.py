"""Input hardening for untrusted logs and runbook text."""

from __future__ import annotations

import re


_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"assistant\s*:", re.IGNORECASE),
    re.compile(r"忽略.{0,8}(指令|规则|要求)"),
    re.compile(r"(直接|立即).{0,8}(执行|调用).{0,12}(工具|命令)"),
)
_CREDENTIAL = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)


def sanitize_untrusted_text(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    safe = text
    if any(pattern.search(text) for pattern in _INJECTION_PATTERNS):
        flags.append("prompt_injection_detected")
        safe = "[UNTRUSTED_INSTRUCTION_REMOVED]"
    if _CREDENTIAL.search(safe):
        flags.append("credential_redacted")
        safe = _CREDENTIAL.sub(lambda match: match.group(1) + "=[REDACTED]", safe)
    return safe, flags


def sanitize_logs(logs: list[str]) -> tuple[list[str], list[str]]:
    cleaned: list[str] = []
    flags: list[str] = []
    for log in logs:
        safe, found = sanitize_untrusted_text(log)
        cleaned.append(safe)
        flags.extend(found)
    return cleaned, sorted(set(flags))
