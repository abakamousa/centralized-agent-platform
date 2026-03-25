import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GuardrailResult:
    sanitized_input: str
    prompt_injection_detected: bool = False
    pii_detected: bool = False
    findings: list[str] = field(default_factory=list)


class PromptInjectionDetectedError(RuntimeError):
    pass


class GuardrailsService:
    PROMPT_INJECTION_PATTERNS = (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?previous\s+instructions",
        r"reveal\s+(the\s+)?system\s+prompt",
        r"show\s+(the\s+)?hidden\s+prompt",
        r"act\s+as\s+an?\s+unrestricted",
        r"bypass\s+(your\s+)?safety",
        r"developer\s+message",
        r"system\s+prompt",
    )

    PII_PATTERNS = {
        "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "phone": re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        prompt_injection = config.get("prompt_injection", {})
        pii_redaction = config.get("pii_redaction", {})

        self.prompt_injection_enabled = bool(prompt_injection.get("enabled", False))
        self.prompt_injection_mode = str(prompt_injection.get("mode", "block"))
        self.pii_redaction_enabled = bool(pii_redaction.get("enabled", False))

    def process(self, user_input: str) -> GuardrailResult:
        result = GuardrailResult(sanitized_input=user_input)

        if self.prompt_injection_enabled and self._detect_prompt_injection(user_input):
            result.prompt_injection_detected = True
            result.findings.append("prompt_injection")
            if self.prompt_injection_mode == "block":
                raise PromptInjectionDetectedError(
                    "Prompt injection patterns detected in user input"
                )

        if self.pii_redaction_enabled:
            sanitized_input, pii_detected = self._redact_pii(result.sanitized_input)
            result.sanitized_input = sanitized_input
            result.pii_detected = pii_detected
            if pii_detected:
                result.findings.append("pii_redacted")

        return result

    def _detect_prompt_injection(self, user_input: str) -> bool:
        lowered = user_input.lower()
        return any(re.search(pattern, lowered) for pattern in self.PROMPT_INJECTION_PATTERNS)

    def _redact_pii(self, user_input: str) -> tuple[str, bool]:
        sanitized = user_input
        pii_detected = False
        for label, pattern in self.PII_PATTERNS.items():
            replacement = f"[REDACTED_{label.upper()}]"
            updated = pattern.sub(replacement, sanitized)
            if updated != sanitized:
                pii_detected = True
                sanitized = updated
        return sanitized, pii_detected
