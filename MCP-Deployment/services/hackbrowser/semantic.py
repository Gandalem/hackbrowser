"""Small, safety-conscious vocabulary for AI-friendly GUI observations.

The Playwright worker owns actual ElementHandles; this module never stores
browser credentials, selectors, screenshots or the user's typed values.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_OBSERVED_ELEMENTS = 80
SNAPSHOT_TTL_SECONDS = 90
_SEARCH_TERMS = re.compile(
    r"(search|query|keyword|find|검색|검색어|검색창|찾기|(^|\W)q($|\W))",
    re.IGNORECASE,
)
_SAFE_BUTTON = re.compile(
    r"(search|검색|find|찾기|sort|정렬|filter|필터|next|다음|previous|"
    r"이전|more|더보기|expand|펼치기|collapse|접기|tab|탭|보기)",
    re.IGNORECASE,
)
_RISKY_LABEL = re.compile(
    r"(결제|구매|주문|삭제|탈퇴|로그아웃|송금|이체|저장|확인.*결제|"
    r"pay|purchase|checkout|buy now|place order|delete|remove|"
    r"sign out|logout|transfer|unsubscribe|submit payment)",
    re.IGNORECASE,
)
_BLOCKED_INPUT = re.compile(
    r"(password|passcode|token|otp|card|cvc|cvv|credit|secret|"
    r"비밀번호|인증번호|카드번호|계좌|주민번호|전화번호|이메일|email|address|주소)",
    re.IGNORECASE,
)


def public_https(url: str) -> bool:
    """Enforce a conservative navigable URL policy; do not fetch it."""
    from workflow_engine import safe_public_url
    return safe_public_url(url)


def is_search_field(details: dict) -> bool:
    if details.get("tag") != "input" or details.get("type") not in {
        "text", "search"
    }:
        return False
    label = str(details.get("name", "")) + " " + str(details.get("label", ""))
    if _BLOCKED_INPUT.search(label):
        return False
    return bool(_SEARCH_TERMS.search(label))


def allow_action(action: str, details: dict) -> tuple[bool, str]:
    """Allow only read-only browsing or safe GET search interactions.

    This is defense-in-depth, not a security guarantee against untrusted
    JavaScript on a site. The user still controls every MCP tool invocation.
    """
    if details.get("disabled"):
        return False, "Element is disabled"
    label = str(details.get("label", ""))
    if _RISKY_LABEL.search(label):
        return False, "Sensitive action requires explicit user-controlled tools"
    if action in {"fill", "search"}:
        if not is_search_field(details):
            return False, "Only non-sensitive search inputs may be filled"
        if action == "search":
            if (not details.get("form_exists") or
                    details.get("form_method") != "get" or
                    details.get("form_has_password") or
                    not public_https(str(details.get("form_action", "")))):
                return False, "Search submission requires a safe GET search form"
        return True, ""
    if action == "click":
        if details.get("tag") == "a":
            href = str(details.get("href", ""))
            if not public_https(href) or details.get("download"):
                return False, "Link destination is not a public HTTPS page"
            return True, ""
        if details.get("tag") == "button" or details.get("role") == "button":
            # A button can run arbitrary JavaScript, so accept only obviously
            # navigational labels and refuse forms which submit via POST.
            if not label or not _SAFE_BUTTON.search(label):
                return False, "Button is not a recognizable browsing control"
            if (details.get("form_exists") and
                    details.get("form_method") != "get"):
                return False, "POST-form buttons need an explicit user action"
            return True, ""
    return False, "Unsupported semantic action"


def clean_public_details(details: dict, ref: str) -> dict:
    """Do not leak form values or sensitive URL query parameters to the model."""
    result = {
        "ref": ref,
        "role": str(details.get("role", ""))[:32],
        "name": str(details.get("label", ""))[:120],
        "tag": str(details.get("tag", ""))[:16],
        "disabled": bool(details.get("disabled")),
    }
    if details.get("type"):
        result["type"] = str(details["type"])[:32]
    href = details.get("href")
    if isinstance(href, str) and href:
        try:
            parsed = urlsplit(href)
            if parsed.scheme in {"https", "http"}:
                result["destination"] = parsed.netloc + parsed.path[:80]
        except ValueError:
            pass
    return result


# Inspect only interactive elements. No values or hidden fields are returned.
DESCRIBE_ELEMENT_JS = r"""(el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' ||
        rect.width <= 0 || rect.height <= 0 ||
        el.closest('[hidden],[aria-hidden="true"]')) return null;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : '')).toLowerCase();
    if (['password', 'hidden', 'file', 'tel', 'email', 'number'].includes(type)) return null;
    const named = el.getAttribute('aria-labelledby');
    const fromLabel = named ? named.split(/\s+/).map(id =>
      document.getElementById(id)?.textContent || '').join(' ') : '';
    const label = fromLabel ||
      el.getAttribute('aria-label') ||
      (el.labels?.length ? Array.from(el.labels).map(x => x.innerText).join(' ') : '') ||
      el.getAttribute('placeholder') ||
      el.innerText || el.getAttribute('title') || el.getAttribute('alt') ||
      el.getAttribute('name') || '';
    const cleaned = label.replace(/\s+/g, ' ').trim().slice(0, 180);
    const role = el.getAttribute('role') ||
      ({ a:'link',button:'button',select:'combobox',textarea:'textbox' }[tag] ||
       (type === 'search' ? 'searchbox' : (tag === 'input' ? 'textbox' : '')));
    const form = el.form || el.closest('form');
    return {
      tag, type, role, label:cleaned,
      name: el.getAttribute('name') || '',
      href: tag === 'a' ? el.href : '',
      download: tag === 'a' && el.hasAttribute('download'),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      form_exists: !!form,
      form_method: form ? (form.getAttribute('method') || 'get').toLowerCase() : '',
      form_action: form ? form.action : '',
      form_has_password: !!(form && form.querySelector('input[type="password"]')),
    };
}"""
