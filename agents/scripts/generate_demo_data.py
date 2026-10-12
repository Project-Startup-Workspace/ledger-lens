"""Generate the synthetic demo cases: notebook page images, wallet statements and labels.

Every person, business and figure here is invented. For each notebook page the script
also writes the offline fixture (what Gemini would return) and a ground-truth label file,
so the full pipeline and the evaluation harness run without network access.

One line per page is drawn as a smudge and recorded with low confidence and a misread
amount, so the review queue and the accuracy report have something real to show.

Run from the repo root: `uv run --project agents python agents/scripts/generate_demo_data.py`
"""

import csv
import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ledger_lens.evidence.schemas import WireEntry, WireExtraction
from ledger_lens.shared.llm import Attachment, fixture_key

ROOT = Path(__file__).resolve().parents[2] / "demo-data"
FONTS = Path("/usr/share/fonts/truetype")
LATIN_FONT = FONTS / "msttcorefonts" / "comic.ttf"
SINHALA_FONT = FONTS / "noto" / "NotoSansSinhala-Regular.ttf"

PAGE_W, PAGE_H = 1000, 1400
TOP, LINE_H, LINES_PER_PAGE = 190, 56, 20
COL_DATE, COL_DESC, COL_IN, COL_OUT = 70, 200, 600, 800
FIRST_MONDAY = date(2026, 8, 10)


@dataclass
class Line:
    day: date
    description: str
    amount: int
    direction: str  # "in" or "out"


@dataclass
class CaseSpec:
    slug: str
    script: str
    language: str
    currency: str
    font: Path
    title: str
    headers: tuple[str, str, str, str]
    words: dict[str, str]
    weeks: int
    daily_sales: tuple[int, int]
    stock_purchase: tuple[int, int]
    utilities: int
    rent: int
    thousands_sep: str
    wallet_share: float | None  # share of sales received by wallet; None means no wallet
    inflate_week: int | None = None  # week index whose notebook sales are inflated
    case: dict[str, object] = field(default_factory=dict)


CASES = [
    CaseSpec(
        slug="synthetic-warung-jakarta",
        script="Latin",
        language="id",
        currency="IDR",
        font=LATIN_FONT,
        title="Buku Kas Warung Bu Siti",
        headers=("Tgl", "Keterangan", "Masuk", "Keluar"),
        words={"sales": "Penjualan", "stock": "Belanja stok", "power": "Listrik", "rent": "Sewa"},
        weeks=8,
        daily_sales=(1_150_000, 1_900_000),
        stock_purchase=(3_200_000, 4_400_000),
        utilities=450_000,
        rent=1_500_000,
        thousands_sep=".",
        wallet_share=0.36,
        inflate_week=5,
        case={
            "jurisdiction": "lk",
            "applicant": {
                "full_name": "Siti Rahayu",
                "date_of_birth": "1986-04-17",
                "national_id": "3174015704860002",
                "phone": "+62 812 5550 1234",
                "business_name": "Warung Bu Siti",
                "business_type": "grocery kiosk",
                "years_in_business": 6,
                "preferred_language": "id",
                "guarantor_name": "Agus Santoso",
            },
            "loan": {
                "amount": 15_000_000,
                "currency": "IDR",
                "tenor_months": 12,
                "annual_rate_pct": 26,
                "purpose": "Second refrigerator for drinks",
            },
        },
    ),
    CaseSpec(
        slug="synthetic-grocer-kandy",
        script="Sinhala",
        language="si",
        currency="LKR",
        font=SINHALA_FONT,
        title="කඩේ ගිණුම් පොත",
        headers=("දිනය", "විස්තරය", "ලැබීම්", "ගෙවීම්"),
        words={
            "sales": "විකුණුම්",
            "stock": "බඩු මිලදී ගැනීම",
            "power": "විදුලි බිල",
            "rent": "කුලිය",
        },
        weeks=8,
        daily_sales=(14_000, 21_000),
        stock_purchase=(38_000, 52_000),
        utilities=6_500,
        rent=25_000,
        thousands_sep=",",
        wallet_share=0.48,
        case={
            "jurisdiction": "lk",
            "applicant": {
                "full_name": "Kamala Perera",
                "date_of_birth": "1979-11-02",
                "national_id": "797063456V",
                "phone": "0771234567",
                "business_name": "Kamala Stores",
                "business_type": "grocery shop",
                "years_in_business": 11,
                "preferred_language": "si",
                "guarantor_name": "Sunil Perera",
            },
            "loan": {
                "amount": 250_000,
                "currency": "LKR",
                "tenor_months": 18,
                "annual_rate_pct": 28,
                "purpose": "Bulk rice and dhal stock before the festival season",
            },
        },
    ),
    CaseSpec(
        slug="synthetic-market-stall-hcmc",
        script="Latin",
        language="vi",
        currency="VND",
        font=LATIN_FONT,
        title="Sổ thu chi - Sạp chị Lan",
        headers=("Ngày", "Nội dung", "Thu", "Chi"),
        words={"sales": "Bán hàng", "stock": "Nhập hàng", "power": "Tiền điện", "rent": "Tiền sạp"},
        weeks=4,
        daily_sales=(900_000, 3_100_000),
        stock_purchase=(4_500_000, 7_500_000),
        utilities=300_000,
        rent=2_000_000,
        thousands_sep=".",
        wallet_share=None,
        case={
            "jurisdiction": "sg",
            "applicant": {
                "full_name": "Nguyen Thi Lan",
                "date_of_birth": "2001-03-09",
                "national_id": "079301001234",
                "phone": "+84 90 555 0199",
                "business_name": "Sap Chi Lan",
                "business_type": "market stall, fruit",
                "years_in_business": 1.5,
                "preferred_language": "vi",
                "guarantor_name": "Tran Van Hung",
            },
            "loan": {
                "amount": 30_000_000,
                "currency": "VND",
                "tenor_months": 9,
                "annual_rate_pct": 30,
                "purpose": "Cold storage boxes",
            },
        },
    ),
]


def ledger_lines(spec: CaseSpec, rng: random.Random) -> list[Line]:
    """Daily sales most days, stock twice a week, utilities and rent once a month."""
    lines: list[Line] = []
    for week in range(spec.weeks):
        monday = FIRST_MONDAY + timedelta(weeks=week)
        inflate = 2.3 if week == spec.inflate_week else 1.0
        for offset in range(7):
            day = monday + timedelta(days=offset)
            if offset == 6 and rng.random() < 0.6:
                continue  # shop often shut on Sunday: no line rather than a zero
            sales = rng.randint(*spec.daily_sales) * inflate
            lines.append(Line(day, spec.words["sales"], int(round(sales, -3)), "in"))
            if offset in (1, 4):
                stock = rng.randint(*spec.stock_purchase)
                lines.append(Line(day, spec.words["stock"], round(stock, -3), "out"))
            if day.day == 5:
                lines.append(Line(day, spec.words["power"], spec.utilities, "out"))
            if day.day == 1:
                lines.append(Line(day, spec.words["rent"], spec.rent, "out"))
    return lines


def fmt(amount: int, sep: str) -> str:
    return f"{amount:,}".replace(",", sep)


def draw_page(
    spec: CaseSpec, lines: list[Line], page_no: int, rng: random.Random
) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
    """Draw one ruled page and return it with each amount's pixel box."""
    img = Image.new("RGB", (PAGE_W, PAGE_H), (250, 247, 236))
    pen = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(spec.font), 30, layout_engine=ImageFont.Layout.RAQM)
    digits = ImageFont.truetype(str(LATIN_FONT), 30)
    title_font = ImageFont.truetype(str(spec.font), 40, layout_engine=ImageFont.Layout.RAQM)
    ink = (28, 42, 110)

    for y in range(TOP, PAGE_H - 40, LINE_H):
        pen.line([(40, y + LINE_H - 8), (PAGE_W - 40, y + LINE_H - 8)], fill=(170, 200, 225))
    pen.line([(COL_IN - 20, 120), (COL_IN - 20, PAGE_H - 40)], fill=(225, 160, 160), width=2)
    pen.text((70, 50), f"{spec.title} — {page_no}", font=title_font, fill=ink)
    for x, header in zip((COL_DATE, COL_DESC, COL_IN, COL_OUT), spec.headers, strict=True):
        pen.text((x, 130), header, font=font, fill=ink)

    boxes: list[tuple[int, int, int, int]] = []
    for i, line in enumerate(lines):
        y = TOP + i * LINE_H + rng.randint(-4, 4)
        jitter = rng.randint(-6, 6)
        pen.text((COL_DATE + jitter, y), line.day.strftime("%d/%m"), font=digits, fill=ink)
        pen.text((COL_DESC + jitter, y), line.description, font=font, fill=ink)
        x = (COL_IN if line.direction == "in" else COL_OUT) + jitter
        text = fmt(line.amount, spec.thousands_sep)
        pen.text((x, y), text, font=digits, fill=ink)
        boxes.append(tuple(int(v) for v in pen.textbbox((x, y), text, font=digits)))  # type: ignore[arg-type]
    return img.rotate(rng.uniform(-0.8, 0.8), fillcolor=(250, 247, 236)), boxes


def smudge(img: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Blur one amount so it looks like a water stain."""
    region = (box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6)
    img.paste(img.crop(region).filter(ImageFilter.GaussianBlur(3.2)), region[:2])
    return img


def misread(amount: int) -> int:
    """A plausible misreading: two adjacent leading digits swapped."""
    digits = list(str(amount))
    if len(digits) > 2 and digits[0] != digits[1]:
        digits[0], digits[1] = digits[1], digits[0]
        return int("".join(digits))
    return amount + 10 ** (len(digits) - 2)


def write_case(spec: CaseSpec, rng: random.Random) -> None:
    out = ROOT / spec.slug
    (out / "labels").mkdir(parents=True, exist_ok=True)
    (ROOT / "fixtures").mkdir(parents=True, exist_ok=True)
    lines = ledger_lines(spec, rng)

    for page_no, start in enumerate(range(0, len(lines), LINES_PER_PAGE), start=1):
        page = lines[start : start + LINES_PER_PAGE]
        img, boxes = draw_page(spec, page, page_no, rng)
        smudged = rng.randrange(len(page))
        img = smudge(img, boxes[smudged])
        name = f"notebook-p{page_no}.png"
        img.save(out / name, optimize=True)

        entries = []
        for i, (line, box) in enumerate(zip(page, boxes, strict=True)):
            is_smudged = i == smudged
            entries.append(
                WireEntry(
                    date=line.day.isoformat(),
                    description=line.description,
                    amount=misread(line.amount) if is_smudged else line.amount,
                    direction=line.direction,  # type: ignore[arg-type]
                    confidence=0.42 if is_smudged else round(rng.uniform(0.86, 0.99), 2),
                    box_2d=[
                        round(box[1] / PAGE_H * 1000),
                        round(box[0] / PAGE_W * 1000),
                        round(box[3] / PAGE_H * 1000),
                        round(box[2] / PAGE_W * 1000),
                    ],
                    raw_text=f"{line.day:%d/%m} {line.description} {line.amount}",
                )
            )
        extraction = WireExtraction(
            script=spec.script,
            language=spec.language,
            currency=spec.currency,
            entries=entries,
            other_text=f"{spec.title} — {page_no}",
            warnings=["One amount is blurred by a stain."],
        )
        data = (out / name).read_bytes()
        key = fixture_key("extract_notebook", [Attachment(data, "image/png")], "")
        (ROOT / "fixtures" / f"{key}.json").write_text(extraction.model_dump_json(indent=2) + "\n")
        labels = [
            {"date": ln.day.isoformat(), "amount": ln.amount, "direction": ln.direction}
            for ln in page
        ]
        label_doc = {"image": name, "script": spec.script, "entries": labels}
        (out / "labels" / f"notebook-p{page_no}.json").write_text(json.dumps(label_doc, indent=2))

    if spec.wallet_share is not None:
        write_wallet(spec, lines, out, rng)
    (out / "case.json").write_text(json.dumps(spec.case, indent=2, ensure_ascii=False) + "\n")


def write_wallet(spec: CaseSpec, lines: list[Line], out: Path, rng: random.Random) -> None:
    """Wallet inflows track a share of genuine sales; inflated notebook weeks are not followed."""
    assert spec.wallet_share is not None
    rows = []
    for line in lines:
        if line.direction != "in":
            continue
        week = (line.day - FIRST_MONDAY).days // 7
        genuine = line.amount / 2.3 if week == spec.inflate_week else line.amount
        inflow = round(genuine * spec.wallet_share * rng.uniform(0.85, 1.15), -2)
        rows.append([line.day.isoformat(), "QR payments received", int(inflow), "in"])
        if rng.random() < 0.25:
            rows.append([line.day.isoformat(), "Transfer to supplier", int(inflow * 0.6), "out"])
    with (out / "wallet-statement.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "description", "amount", "direction"])
        writer.writerows(rows)


def main() -> None:
    for spec in CASES:
        write_case(spec, random.Random(hashlib.sha256(spec.slug.encode()).digest()))
        print(f"wrote {spec.slug}")


if __name__ == "__main__":
    main()
