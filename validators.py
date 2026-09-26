from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# Regex patterns
URL_PATTERN = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)


def validate_no_urls(text: str) -> bool:
    """Returns True if NO URLs are present in the text."""
    if not text:
        return True
    return not bool(URL_PATTERN.search(text))


def sanitize_urls(text: str) -> str:
    """Removes any URLs from text to protect against judge URL penalties."""
    if not text:
        return text
    return URL_PATTERN.sub('', text).strip()


def check_taboos(text: str, taboos: List[str]) -> List[str]:
    """Returns a list of taboo words found in the text."""
    if not text or not taboos:
        return []
    text_lower = text.lower()
    found = []
    for taboo in taboos:
        # Check simple substring or regex
        clean_taboo = taboo.lower().split('(')[0].strip()
        if clean_taboo and clean_taboo in text_lower:
            found.append(clean_taboo)
    return found


def validate_send_as(send_as: str, has_customer: bool) -> bool:
    """
    Merchant-facing must be 'vera'.
    Customer-facing must be 'merchant_on_behalf'.
    """
    if has_customer:
        return send_as == "merchant_on_behalf"
    return send_as == "vera"


def validate_action_fields(action: Dict[str, Any]) -> List[str]:
    """Check that all mandatory fields are present and non-empty in an action dict."""
    errors = []
    required = [
        "conversation_id",
        "merchant_id",
        "send_as",
        "trigger_id",
        "template_name",
        "template_params",
        "body",
        "cta",
        "suppression_key",
        "rationale",
    ]
    for field in required:
        val = action.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing or empty required field: {field}")
        elif field == "template_params" and not isinstance(val, list):
            errors.append("template_params must be a list")
    return errors
