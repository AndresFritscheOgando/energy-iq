"""Deterministic checks on a model proposal (spec 0012/0004 AC-2, AC-3).

The model is never the judge of its own answer. Every value is normalized by
code, every quote is compared with the retained page text, and numbers and
dates must appear in their quote. A value that fails is dropped and its issue
code stays visible. A value that passes is still only a candidate: a person
confirms it, so ``requires_review`` is always true and nothing is auto accepted.
Page text is read here as plain data; no text is ever treated as an instruction.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from energyiq.documents.pdf_text import ParsedPage
from energyiq.extraction.schema import (
    FIELD_NAMES,
    Evidence,
    FieldName,
    Proposal,
)
from energyiq.properties.models import Distributor

MAX_KWH = Decimal(1000000)
MAX_MONEY = Decimal(100000000)
MAX_PERIOD_DAYS = 366
# A numeric or date quote is one printed line, not a block that happens to hold
# the number. A longer quote fails instead of verifying for any number inside it.
MAX_NUMERIC_QUOTE = 120

_KWH = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,6})?$")
_MONEY = re.compile(r"^[0-9]{1,14}(\.[0-9]{1,2})?$")
_CLASS = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,15}$")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DMY = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)")
_WORDS = re.compile(
    r"(?<!\d)(\d{1,2})[\s\-/.]+(?:de\s+)?([A-Za-zÀ-ÿ]{3,10})\.?[\s\-/.]+(?:de\s+)?(\d{4})(?!\d)"
)
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
# A sign counts only when it touches the number or marker, or follows a colon.
# "Total a pagar - RD$ 5" uses the dash as a separator, not as a minus sign.
_KWH_AT = re.compile(
    r"(?P<sign>[-−]?)\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*kwh\b"
    r"|\bkwh\s*[:=]?\s*(?P<sign3>[-−]?)(?P<num2>\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
_MONEY_AT = re.compile(
    r"(?P<sign>[-−]?)\s*(?<![A-Za-z])(?:rd\s*\$|dop|\$)\)?\s*(?P<sign2>[-−]?)\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"|(?P<sign3>[-−]?)\s*(?P<num2>\d[\d,]*(?:\.\d+)?)\s*dop\b",
    re.IGNORECASE,
)
# Another currency anywhere in the quote means the amount is not DOP.
_OTHER_CURRENCY = re.compile(r"us\s*\$|\busd\b|\beur\b|€", re.IGNORECASE)
# The quote must carry the field's own label and none of a look alike label, so
# a subtotal, a fixed charge, or a previous reading cannot stand for the real field.
_LABELS: dict[str, tuple[re.Pattern[str], re.Pattern[str] | None]] = {
    "billed_kwh": (
        re.compile(r"consumo|facturad", re.IGNORECASE),
        re.compile(r"lectura|acumul|promedio|demanda|anterior|potencia", re.IGNORECASE),
    ),
    "total_dop": (
        re.compile(r"\btotal\b|a pagar|monto|importe", re.IGNORECASE),
        re.compile(
            r"sub\s*-?\s*total|anterior|pendiente|mora|recargo|descuento"
            r"|impuesto|itbis|energ[ií]a",
            re.IGNORECASE,
        ),
    ),
    "energy_charge_dop": (
        re.compile(r"\benerg[ií]a\b", re.IGNORECASE),
        re.compile(
            r"fijo|mora|recargo|alumbrado|comercializ|potencia|total|impuesto|itbis",
            re.IGNORECASE,
        ),
    ),
    "period_start": (
        re.compile(r"\bdesde\b|\binicio\b|\binicial\b|\bdel\b", re.IGNORECASE),
        re.compile(r"\bhasta\b|\bfin\b|\bfinal\b", re.IGNORECASE),
    ),
    "period_end": (
        re.compile(r"\bhasta\b|\bfin\b|\bfinal\b|\bal\b", re.IGNORECASE),
        re.compile(r"\bdesde\b|\binicio\b|\binicial\b", re.IGNORECASE),
    ),
    "issue_date": (
        re.compile(r"emisi|emitid|factur", re.IGNORECASE),
        re.compile(r"venc|l[ií]mite", re.IGNORECASE),
    ),
    "due_date": (
        re.compile(r"venc|l[ií]mite", re.IGNORECASE),
        re.compile(r"emisi|emitid", re.IGNORECASE),
    ),
}
_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}  # fmt: skip

_DATES: tuple[FieldName, ...] = ("period_start", "period_end", "issue_date", "due_date")
_KWH_FIELDS: tuple[FieldName, ...] = ("billed_kwh",)
_MONEY_FIELDS: tuple[FieldName, ...] = ("total_dop", "energy_charge_dop")


@dataclass(frozen=True)
class ValidatedField:
    name: FieldName
    state: str
    value: str | None
    quote: str | None
    page_number: int | None
    start: int | None
    end: int | None
    uncertainty: str | None
    issues: tuple[str, ...]
    evidence_verified: bool

    def to_json(self) -> dict[str, object]:
        return {
            "state": self.state,
            "value": self.value,
            "quote": self.quote,
            "page_number": self.page_number,
            "start": self.start,
            "end": self.end,
            "uncertainty": self.uncertainty,
            "issues": list(self.issues),
            "evidence_verified": self.evidence_verified,
        }


@dataclass(frozen=True)
class ValidatedContradiction:
    field: FieldName
    candidates: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ValidatedProposal:
    fields: dict[FieldName, ValidatedField]
    contradictions: tuple[ValidatedContradiction, ...]
    conflicts: tuple[tuple[str, tuple[FieldName, ...]], ...]

    # A proposal is never a confirmed invoice. The review step is not optional.
    requires_review = True

    def to_json(self) -> dict[str, object]:
        return {
            "fields": {n: f.to_json() for n, f in self.fields.items()},
            "contradictions": [
                {"field": c.field, "candidates": list(c.candidates)}
                for c in self.contradictions
            ],
            "conflicts": [
                {"code": code, "fields": list(names)} for code, names in self.conflicts
            ],
            "requires_review": True,
        }


Span = tuple[int, int] | None


def _check_evidence(
    item: Evidence, pages: dict[int, ParsedPage], *, required: bool
) -> tuple[bool, list[str], Span]:
    """Verify a quote against page text; returns the verified span, if any.

    A model cannot count characters reliably, so a quote and page with no
    offsets are located by code. Only one exact match counts: zero matches is a
    mismatch and several is ambiguous, never a guess.
    """
    given = [item.quote, item.page_number, item.start, item.end]
    if all(part is None for part in given):
        return False, (["evidence_missing"] if required else []), None
    if item.quote is None or item.page_number is None:
        return False, ["evidence_incomplete"], None
    if (item.start is None) != (item.end is None):
        return False, ["evidence_incomplete"], None
    page = pages.get(item.page_number)
    if page is None:
        return False, ["evidence_page_unknown"], None
    text = page.normalized_text
    if item.start is None or item.end is None:
        first = text.find(item.quote) if item.quote else -1
        if first < 0:
            return False, ["evidence_quote_mismatch"], None
        if text.find(item.quote, first + 1) >= 0:
            return False, ["evidence_ambiguous"], None
        return True, [], (first, first + len(item.quote))
    if not 0 <= item.start < item.end <= len(text):
        return False, ["evidence_span_invalid"], None
    if text[item.start : item.end] != item.quote:
        return False, ["evidence_quote_mismatch"], None
    return True, [], (item.start, item.end)


def _decimal(
    text: str, pattern: re.Pattern[str], ceiling: Decimal
) -> tuple[str | None, str | None]:
    text = text.strip()
    if text.startswith("-"):
        return None, "value_negative"
    if not pattern.match(text):
        return None, "value_invalid"
    try:
        number = Decimal(text)
    except InvalidOperation:  # pragma: no cover - the pattern already blocks this
        return None, "value_invalid"
    if number > ceiling:
        return None, "value_out_of_range"
    return text, None


def _is_negative(quote: str, match: re.Match[str]) -> bool:
    """A minus sign, or an amount in brackets.

    A dash counts as a minus when it touches what follows it, or when it opens
    the quote or follows a colon or bracket. A spaced dash after a word is a
    separator ("Total a pagar - RD$ 5").
    """
    before = quote[: match.start()].rstrip()
    after = quote[match.end() :].lstrip()
    if before.endswith("(") and after.startswith(")"):
        return True
    for key in ("sign", "sign2", "sign3"):
        if not match.groupdict().get(key):
            continue
        end = match.end(key)
        tight = end < len(quote) and not quote[end].isspace()
        pre = quote[: match.start(key)].rstrip()
        if tight or not pre or pre[-1] in ":(=":
            return True
    return False


def _amounts(pattern: re.Pattern[str], quote: str) -> list[tuple[bool, Decimal]]:
    """Every amount in ``quote`` that carries the field's unit, with its sign."""
    found: list[tuple[bool, Decimal]] = []
    for match in pattern.finditer(quote):
        parts = match.groupdict()
        number = parts.get("num") or parts.get("num2")
        if number is None:
            continue
        try:
            found.append((_is_negative(quote, match), Decimal(number.replace(",", ""))))
        except InvalidOperation:
            continue
    return found


def _amount_issue(value: str, amounts: list[tuple[bool, Decimal]]) -> str | None:
    if not amounts:
        return "unit_missing"
    wanted = Decimal(value)
    distinct = {number for _, number in amounts}
    if wanted not in distinct:
        return "value_not_in_quote"
    if len(distinct) > 1:
        return "value_ambiguous_in_quote"
    if any(negative for negative, number in amounts if number == wanted):
        return "value_negative"
    return None


def _dates_in(quote: str) -> list[date]:
    """Dates in the order they are printed, each once."""
    hits: list[tuple[int, date]] = []

    def add(position: int, year: int, month: int, day: int) -> None:
        try:
            hits.append((position, date(year, month, day)))
        except ValueError:
            return

    for m in _ISO.finditer(quote):
        add(m.start(), int(m[1]), int(m[2]), int(m[3]))
    for m in _DMY.finditer(quote):  # day first, as printed on local bills
        add(m.start(), int(m[3]), int(m[2]), int(m[1]))
    for m in _WORDS.finditer(quote):
        month = _MONTHS.get(m[2].lower()[:3])
        if month:
            add(m.start(), int(m[3]), month, int(m[1]))
    ordered: list[date] = []
    for _, found in sorted(hits):
        if found not in ordered:
            ordered.append(found)
    return ordered


def _label_issue(name: str, quote: str) -> str | None:
    want, reject = _LABELS[name]
    if not want.search(quote):
        return "label_missing"
    if reject is not None and reject.search(quote):
        return "label_conflict"
    return None


def _date_issue(name: FieldName, value: str, quote: str) -> str | None:
    dates = _dates_in(quote)
    wanted = date.fromisoformat(value)
    if name in ("period_start", "period_end"):
        if len(dates) == 2:
            # Two dates are placed by position: first is the start, last the end.
            if wanted not in dates:
                return "value_not_in_quote"
            expected = dates[0] if name == "period_start" else dates[-1]
            return None if wanted == expected else "value_wrong_position"
        if len(dates) > 2:
            return "value_ambiguous_in_quote"
    issue = _label_issue(name, quote)  # a lone date is placed by its own label
    if issue:
        return issue
    if wanted not in dates:
        return "value_not_in_quote"
    return "value_ambiguous_in_quote" if len(dates) > 1 else None


def _normalize(name: FieldName, raw: str) -> tuple[str | None, str | None]:
    if name in _DATES:
        try:
            return date.fromisoformat(raw.strip()).isoformat(), None
        except ValueError:
            return None, "value_invalid"
    if name in _KWH_FIELDS:
        return _decimal(raw, _KWH, MAX_KWH)
    if name in _MONEY_FIELDS:
        return _decimal(raw, _MONEY, MAX_MONEY)
    if name == "distributor":
        try:
            return Distributor(raw.strip().upper()).value, None
        except ValueError:
            return None, "value_invalid"
    text = raw.strip().upper()  # tariff_class
    return (text, None) if _CLASS.match(text) else (None, "value_invalid")


def _context_issue(name: FieldName, value: str, quote: str) -> str | None:
    """Does the quote really say this value for this field?

    A number or date merely appearing somewhere in a quote proves nothing. The
    quote must be one line, carry the field's own label (and no look alike one)
    and its unit, name one value, and keep its sign, so a total cannot pass as
    an energy charge, a subtotal as a total, or a year as kWh.
    """
    if name in _DATES or name in _KWH_FIELDS or name in _MONEY_FIELDS:
        if len(quote) > MAX_NUMERIC_QUOTE:
            return "quote_too_long"
        if "\n" in quote or "\r" in quote:
            return "quote_multiline"
    if name in _DATES:
        return _date_issue(name, value, quote)
    if name in _KWH_FIELDS:
        return _label_issue(name, quote) or _amount_issue(
            value, _amounts(_KWH_AT, quote)
        )
    if name in _MONEY_FIELDS:
        if _OTHER_CURRENCY.search(quote):
            return "currency_not_dop"
        return _label_issue(name, quote) or _amount_issue(
            value, _amounts(_MONEY_AT, quote)
        )
    # distributor and tariff class: the whole value as a word, not a stray letter
    word = r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])"
    return None if re.search(word, quote, re.IGNORECASE) else "value_not_in_quote"


def _check_value(
    name: FieldName,
    raw: str,
    item: Evidence,
    pages: dict[int, ParsedPage],
    *,
    required: bool,
) -> tuple[str | None, bool, list[str], Span]:
    """Normalize one value and test its evidence; shared by fields and candidates."""
    value, problem = _normalize(name, raw)
    issues = [problem] if problem else []
    verified, found, where = _check_evidence(item, pages, required=required)
    issues.extend(found)
    if value is not None and verified and item.quote is not None:
        issue = _context_issue(name, value, item.quote)
        if issue:
            issues.append(issue)
            verified = False
    return value, verified and value is not None, issues, where


def _field(
    name: FieldName, item: Proposal, pages: dict[int, ParsedPage]
) -> ValidatedField:
    prop = item.fields[name]
    issues: list[str] = []
    value: str | None = None
    verified = False
    where: Span = None
    if prop.state == "not_found":
        if prop.value is not None:
            issues.append("state_not_found_has_value")
    elif prop.value is None:
        issues.append("value_missing")
    else:
        value, verified, found, where = _check_value(
            name, prop.value, prop, pages, required=prop.state == "explicit"
        )
        issues.extend(found)
        if prop.state == "inferred":
            issues.append("inferred_requires_review")
    state = prop.state if value is not None else "not_found"
    return ValidatedField(
        name,
        state,
        value,
        prop.quote,
        prop.page_number,
        where[0] if where else prop.start,
        where[1] if where else prop.end,
        prop.uncertainty,
        tuple(issues),
        verified,
    )


def _conflicts(
    fields: dict[FieldName, ValidatedField],
    contradictions: Sequence[ValidatedContradiction],
) -> list[tuple[str, tuple[FieldName, ...]]]:
    found: list[tuple[str, tuple[FieldName, ...]]] = []
    for item in contradictions:
        found.append(("contradiction", (item.field,)))
    start, end = fields["period_start"].value, fields["period_end"].value
    if start and end:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first > last:
            found.append(("period_inverted", ("period_start", "period_end")))
        elif (last - first).days > MAX_PERIOD_DAYS:
            found.append(("period_too_long", ("period_start", "period_end")))
    issue, due = fields["issue_date"].value, fields["due_date"].value
    if issue and due and date.fromisoformat(due) < date.fromisoformat(issue):
        found.append(("due_before_issue", ("issue_date", "due_date")))
    total, charge = fields["total_dop"].value, fields["energy_charge_dop"].value
    if total and charge and Decimal(charge) > Decimal(total):
        found.append(("energy_exceeds_total", ("energy_charge_dop", "total_dop")))
    return found


def validate_proposal(
    proposal: Proposal, pages: Sequence[ParsedPage]
) -> ValidatedProposal:
    by_number = {page.page_number: page for page in pages}
    fields: dict[FieldName, ValidatedField] = {
        name: _field(name, proposal, by_number) for name in FIELD_NAMES
    }
    contradictions: list[ValidatedContradiction] = []
    for contradiction in proposal.contradictions:
        candidates: list[dict[str, Any]] = []
        for candidate in contradiction.candidates:
            value, ok, issues, where = _check_value(
                contradiction.field,
                candidate.value,
                candidate,
                by_number,
                required=True,
            )
            candidates.append(
                {
                    "value": value,
                    "raw_value": candidate.value if value is None else None,
                    "quote": candidate.quote,
                    "page_number": candidate.page_number,
                    "start": where[0] if where else candidate.start,
                    "end": where[1] if where else candidate.end,
                    "evidence_verified": ok,
                    "issues": issues,
                }
            )
        contradictions.append(
            ValidatedContradiction(contradiction.field, tuple(candidates))
        )
    # A field with a contradiction is visibly marked, whatever the model chose.
    for item in contradictions:
        current = fields[item.field]
        fields[item.field] = ValidatedField(
            current.name,
            current.state,
            current.value,
            current.quote,
            current.page_number,
            current.start,
            current.end,
            current.uncertainty,
            (*current.issues, "contradiction"),
            False,
        )
    return ValidatedProposal(
        fields, tuple(contradictions), tuple(_conflicts(fields, contradictions))
    )
