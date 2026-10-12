"""Personal data must never reach logs in plain text."""

import json
import logging

import pytest

from ledger_lens.shared.logs import JsonFormatter, case_context
from ledger_lens.shared.pii import mask_text, pseudonym


@pytest.mark.parametrize(
    ("raw", "hidden"),
    [
        ("call +94 77 123 4567 today", "+94 77 123 4567"),
        ("call 0771234567 today", "0771234567"),
        ("NIC 912345678V", "912345678V"),
        ("NIC 199123456789", "199123456789"),
        ("NRIC S1234567D", "S1234567D"),
        ("NIK 3174012345678901", "3174012345678901"),
        ("mail siti@example.com", "siti@example.com"),
    ],
)
def test_mask_text_hides_identifiers(raw: str, hidden: str) -> None:
    assert hidden not in mask_text(raw)


def test_mask_text_keeps_amounts() -> None:
    assert mask_text("weekly sales 125000 LKR") == "weekly sales 125000 LKR"


def test_mask_text_hides_known_names_case_insensitively() -> None:
    assert mask_text("Applicant SITI rahma", ("Siti Rahma",)) == "Applicant [name]"


def test_pseudonym_is_stable_and_opaque() -> None:
    assert pseudonym(" Siti ") == pseudonym("siti")
    assert "siti" not in pseudonym("siti")


def test_json_formatter_adds_case_id_and_masks_extras() -> None:
    record = logging.makeLogRecord(
        {"msg": "read notebook for Siti Rahma", "levelname": "INFO", "phone": "0771234567"}
    )
    with case_context("case_1", names=("Siti Rahma",)):
        line = json.loads(JsonFormatter().format(record))
    assert line["case_id"] == "case_1"
    assert "Siti" not in line["message"]
    assert line["phone"] == "[phone]"
