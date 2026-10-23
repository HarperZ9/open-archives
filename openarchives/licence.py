# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Licence normalisation and the rights-basis gate.

Two layers:
  licence class  what the source says (normalised from text or a URL)
  rights basis   what we may do with it; the gate is explicit and
                 anything unclear becomes reference-only.
"""
from __future__ import annotations

import re

# Normalised licence classes.
PD = "pd"
CC0 = "cc0"
CC_BY = "cc-by"
CC_BY_SA = "cc-by-sa"
NC = "nc"                # any CC NonCommercial variant
ND = "nd"                # CC NoDerivatives without NC
OFL = "ofl"              # SIL Open Font License
PERMISSIVE = "permissive"  # MIT, Apache-2.0, BSD and similar (datasets, code)
NKR = "nkr"              # "no known restrictions" (LoC style); not a licence
OTHER_OPEN = "other-open"  # GFDL, Free Art and other open but awkward terms
IN_COPYRIGHT = "in-copyright"
UNKNOWN = "unknown"
LICENCE_CLASSES = (PD, CC0, CC_BY, CC_BY_SA, NC, ND, OFL, PERMISSIVE, NKR,
                   OTHER_OPEN, IN_COPYRIGHT, UNKNOWN)

# Rights bases (what an asset may ship on).
FREE = "free"                  # public domain or CC0: ship freely
CREDIT = "credit"              # CC BY, OFL, permissive: ship with credit/notice
SHARE_ALIKE = "share-alike"    # CC BY-SA: ship with credit under share-alike
LICENSED = "licensed"          # the user holds a licence; recorded by hand
FAIR_USE = "fair-use"          # commentary or critique in explainers; recorded by hand
REFERENCE_ONLY = "reference-only"
OWN_WORK = "own-work"          # made by the user; clean-room gate applies
BASES = (FREE, OWN_WORK, CREDIT, SHARE_ALIKE, LICENSED, FAIR_USE, REFERENCE_ONLY)
SHIPPABLE = (FREE, OWN_WORK, CREDIT, SHARE_ALIKE, LICENSED, FAIR_USE)

_BASIS_BY_CLASS = {
    PD: FREE, CC0: FREE,
    CC_BY: CREDIT, OFL: CREDIT, PERMISSIVE: CREDIT,
    CC_BY_SA: SHARE_ALIKE,
}

# Ordered: first match wins. Patterns run on a lowercased, hyphenated string.
_RULES: list[tuple[str, str]] = [
    (r"publicdomain-zero|publicdomain/zero|\bcc0\b|cc-zero|cc-0\b", CC0),
    (r"by-nc|noncommercial|non-commercial|\bnc\b", NC),
    (r"by-nd|noderiv|no-deriv", ND),
    (r"by-sa|sharealike|share-alike", CC_BY_SA),
    (r"licenses/by/|cc-by\b|\bby-\d|^by$|attribution", CC_BY),
    (r"publicdomain/mark|licenses/publicdomain|public-domain|publicdomain|"
     r"\bpdm\b|^pd\b|(^|[^a-z])pd-|vocab/noc-us|no-copyright|copyright-not-evident|"
     r"not-in-copyright|\bpd$", PD),
    (r"no-known-restrictions|no-known-copyright", NKR),
    (r"\bofl\b|open-font-license|sil-open", OFL),
    (r"\bmit\b|apache|bsd-|\bbsd\b|\bisc\b|unlicense|odc-by|cdla-permissive", PERMISSIVE),
    (r"gfdl|free-art|fal-1|odbl|cc-by-3\.0-igo", OTHER_OPEN),
    (r"vocab/inc|in-copyright|all-rights-reserved|copyrighted|©|rights-reserved", IN_COPYRIGHT),
]


def _canon(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("_", "-")
    t = re.sub(r"\s+", "-", t)
    return t


def normalise(*statements: str | None) -> str:
    """Return the licence class for the first statement that matches a rule.

    Statements are tried in order (pass the most authoritative first, for
    example a licence URL before a free-text rights note).
    """
    for statement in statements:
        if not statement:
            continue
        canon = _canon(str(statement))
        for pattern, cls in _RULES:
            if re.search(pattern, canon):
                return cls
    return UNKNOWN


def basis_for(licence_class: str) -> str:
    """The default rights basis for a licence class. Unclear means reference-only."""
    return _BASIS_BY_CLASS.get(licence_class, REFERENCE_ONLY)


def derived_basis(source_bases: list[str]) -> str:
    """Basis of an asset derived from several sources: the most restrictive wins."""
    order = list(BASES)
    if not source_bases:
        return REFERENCE_ONLY
    return max(source_bases, key=order.index)


def attribution(title: str, creator: str | None, source: str,
                licence_class: str, licence_url: str | None,
                landing_url: str | None) -> str:
    """TASL attribution line: Title, Author, Source, Licence."""
    who = f" by {creator}" if creator else ""
    lic = {
        PD: "Public domain", CC0: "CC0 1.0", CC_BY: "CC BY", CC_BY_SA: "CC BY-SA",
        NC: "CC NonCommercial licence", ND: "CC NoDerivatives licence",
        OFL: "SIL Open Font License", PERMISSIVE: "permissive licence",
        NKR: "no known restrictions (not a licence)", OTHER_OPEN: "open licence, see source",
        IN_COPYRIGHT: "in copyright", UNKNOWN: "rights unknown",
    }.get(licence_class, licence_class)
    if licence_url:
        lic = f"{lic} ({licence_url})"
    where = f", {landing_url}" if landing_url else ""
    return f'"{title}"{who}, via {source}{where}. {lic}.'
