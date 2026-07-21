"""ZIP → city/state lookup with offline Chicagoland fallback.

Uses the ``zipcodes`` package when available; falls back to a small in-repo
map so tests and offline environments never regress for Cook County ZIPs.
"""
from __future__ import annotations

import re

_ZIP5_RE = re.compile(r'^(\d{5})(?:-\d{4})?$')

# Minimal Chicagoland / near-suburb map for offline + test stability.
_CHICAGOLAND_FALLBACK: dict[str, tuple[str, str]] = {
    '60601': ('Chicago', 'IL'),
    '60602': ('Chicago', 'IL'),
    '60603': ('Chicago', 'IL'),
    '60604': ('Chicago', 'IL'),
    '60605': ('Chicago', 'IL'),
    '60606': ('Chicago', 'IL'),
    '60607': ('Chicago', 'IL'),
    '60608': ('Chicago', 'IL'),
    '60609': ('Chicago', 'IL'),
    '60610': ('Chicago', 'IL'),
    '60611': ('Chicago', 'IL'),
    '60612': ('Chicago', 'IL'),
    '60613': ('Chicago', 'IL'),
    '60614': ('Chicago', 'IL'),
    '60615': ('Chicago', 'IL'),
    '60616': ('Chicago', 'IL'),
    '60617': ('Chicago', 'IL'),
    '60618': ('Chicago', 'IL'),
    '60619': ('Chicago', 'IL'),
    '60620': ('Chicago', 'IL'),
    '60621': ('Chicago', 'IL'),
    '60622': ('Chicago', 'IL'),
    '60623': ('Chicago', 'IL'),
    '60624': ('Chicago', 'IL'),
    '60625': ('Chicago', 'IL'),
    '60626': ('Chicago', 'IL'),
    '60628': ('Chicago', 'IL'),
    '60629': ('Chicago', 'IL'),
    '60630': ('Chicago', 'IL'),
    '60631': ('Chicago', 'IL'),
    '60632': ('Chicago', 'IL'),
    '60633': ('Chicago', 'IL'),
    '60634': ('Chicago', 'IL'),
    '60636': ('Chicago', 'IL'),
    '60637': ('Chicago', 'IL'),
    '60638': ('Chicago', 'IL'),
    '60639': ('Chicago', 'IL'),
    '60640': ('Chicago', 'IL'),
    '60641': ('Chicago', 'IL'),
    '60642': ('Chicago', 'IL'),
    '60643': ('Chicago', 'IL'),
    '60644': ('Chicago', 'IL'),
    '60645': ('Chicago', 'IL'),
    '60646': ('Chicago', 'IL'),
    '60647': ('Chicago', 'IL'),
    '60649': ('Chicago', 'IL'),
    '60651': ('Chicago', 'IL'),
    '60652': ('Chicago', 'IL'),
    '60653': ('Chicago', 'IL'),
    '60654': ('Chicago', 'IL'),
    '60655': ('Chicago', 'IL'),
    '60656': ('Chicago', 'IL'),
    '60657': ('Chicago', 'IL'),
    '60659': ('Chicago', 'IL'),
    '60660': ('Chicago', 'IL'),
    '60661': ('Chicago', 'IL'),
    '60707': ('Elmwood Park', 'IL'),
    '60714': ('Niles', 'IL'),
    '60076': ('Skokie', 'IL'),
    '60077': ('Skokie', 'IL'),
    '60201': ('Evanston', 'IL'),
    '60202': ('Evanston', 'IL'),
    '60302': ('Oak Park', 'IL'),
    '60304': ('Oak Park', 'IL'),
    '60402': ('Berwyn', 'IL'),
    '60453': ('Oak Lawn', 'IL'),
    '60513': ('Brookfield', 'IL'),
    '60525': ('La Grange', 'IL'),
    '60546': ('Riverside', 'IL'),
}


def normalize_zip5(zip_code: str | None) -> str | None:
    """Return a 5-digit ZIP, or None when the input is not ZIP-shaped."""
    text = (zip_code or '').strip()
    match = _ZIP5_RE.match(text)
    if not match:
        return None
    return match.group(1)


def _title_city_usps(city: str) -> str:
    """Title-case an ALL-CAPS USPS city without mangling Mc*/Mac* prefixes."""
    if not city.isupper():
        return city
    parts: list[str] = []
    for word in city.split():
        upper = word.upper()
        if upper.startswith('MC') and len(upper) > 2:
            parts.append('Mc' + upper[2:].title())
        elif upper.startswith('MAC') and len(upper) > 4:
            parts.append('Mac' + upper[3:].title())
        else:
            parts.append(word.title())
    return ' '.join(parts)


def city_state_from_zip(zip5: str | None) -> tuple[str, str] | None:
    """Resolve ``(city, state)`` for a ZIP5.

    Prefers the ``zipcodes`` package (pinned ``zipcodes==1.2.0`` in
    requirements.txt); falls back to the Chicagoland map below.

    Coverage limits: the offline fallback only covers Cook County / near-suburb
    ZIPs, so a ZIP outside Chicagoland resolves ONLY when the ``zipcodes``
    package is installed. If a deploy drops that dependency, non-Chicago ZIPs
    return None (city/state stay blank) rather than a wrong value — callers must
    treat None as "unknown", not "invalid". Keep the package pinned so
    nationwide coverage is deterministic.

    City is title-cased (Mc*/Mac*-aware); state is a 2-letter uppercase code.
    """
    zip_norm = normalize_zip5(zip5)
    if not zip_norm:
        return None

    try:
        import zipcodes  # type: ignore
        matches = zipcodes.matching(zip_norm)
        if matches:
            city = (matches[0].get('city') or '').strip()
            state = (matches[0].get('state') or '').strip().upper()
            if city and len(state) == 2:
                return _title_city_usps(city), state
    except Exception:
        pass

    return _CHICAGOLAND_FALLBACK.get(zip_norm)
