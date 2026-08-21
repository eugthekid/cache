"""
import_.py
----------
(Named import_.py, not import.py -- `import` is a reserved word, can't be
a module name.)

Spreadsheet import (.xlsx/.csv) as a distinct ingestion source. See
docs/DATA-MODEL.md's "Spreadsheet import" section for the two-mode design
(a purchase vs. stock already held) and why duplicates are matched on
order_number specifically, not source+external_id like Discord ingestion.

Two calls, same preview/commit split as backup.py, for the same reason:
the column-mapping confirmation step needs real detected headers and a
row-by-row preview BEFORE anything is written, and re-uploading for the
actual commit is a small cost for never writing data the user hasn't seen.
Both calls run every row through the exact same _evaluate_all_rows(), so
preview can never show something different from what commit actually does
-- they're not two implementations of the same logic, they're one.
"""

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import openpyxl
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db
from app.models import _now

router = APIRouter(prefix="/import", tags=["import"])

_PURCHASE_FIELDS = {
    "product", "site", "price", "quantity", "order_date",
    "status", "category", "ship_to_label", "order_number",
}
_UNIT_FIELDS = {"product", "price", "quantity", "status", "notes"}

# Header text -> our field, for auto-guessing a mapping (see _guess_mapping).
# Real spreadsheets use whatever words their owner picked, not our column
# names, so this is a curated "words people actually use" list, not
# something fancier -- a wrong guess costs the user one click to fix.
_HEADER_SYNONYMS: dict[str, list[str]] = {
    "product": ["item name", "item", "product", "name", "description"],
    "site": ["store", "site", "retailer", "merchant", "where bought", "seller"],
    "price": ["paid", "price", "cost", "amount", "total"],
    "quantity": ["qty", "quantity", "count"],
    "order_date": ["date bought", "date", "purchase date", "order date", "bought"],
    "status": ["status", "order status", "outcome"],
    "category": ["category", "type"],
    "ship_to_label": ["where", "address", "ship to", "shipped to"],
    "order_number": ["order #", "order number", "order id", "confirmation"],
    "notes": ["notes", "note", "comment", "comments"],
}


def _guess_mapping(headers: list[str], fields: set[str]) -> dict[str, Optional[str]]:
    """One header claims at most one field -- greedy, exact match first,
    substring second -- so two fields never both point at the same
    column."""
    mapping: dict[str, Optional[str]] = {f: None for f in fields}
    claimed: set[str] = set()
    lowered = {h: h.strip().lower() for h in headers}

    for field in fields:
        synonyms = _HEADER_SYNONYMS.get(field, [])
        for header, low in lowered.items():
            if header in claimed:
                continue
            if low in synonyms:
                mapping[field] = header
                claimed.add(header)
                break
        if mapping[field]:
            continue
        for header, low in lowered.items():
            if header in claimed:
                continue
            if any(syn in low or low in syn for syn in synonyms):
                mapping[field] = header
                claimed.add(header)
                break
    return mapping


def _read_rows(
    filename: str, content: bytes, sheet: Optional[str]
) -> tuple[list[str], list[dict], list[str]]:
    """Returns (headers, rows-as-dicts-keyed-by-header, sheet_names).
    sheet_names is always empty for CSV -- there's no such concept."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Couldn't read that file as .xlsx.")
        sheet_names = wb.sheetnames
        if sheet and sheet not in sheet_names:
            raise HTTPException(status_code=400, detail=f"No sheet named '{sheet}' in this file.")
        ws = wb[sheet] if sheet else wb[sheet_names[0]]

        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            return [], [], sheet_names
        headers = [str(h).strip() if h is not None else "" for h in header_row]

        rows = []
        for raw_row in rows_iter:
            if all(v is None for v in raw_row):
                continue
            rows.append({headers[i]: raw_row[i] for i in range(len(headers)) if i < len(raw_row)})
        return headers, rows, sheet_names

    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are supported.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = [row for row in reader if any((v or "").strip() for v in row.values())]
    return headers, rows, []


def _extract(row: dict, mapping: dict[str, Optional[str]], field: str) -> Any:
    col = mapping.get(field)
    if not col:
        return None
    value = row.get(col)
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[\d,]+\.?\d*", str(value))
    return float(match.group().replace(",", "")) if match else None


def _parse_quantity(value: Any) -> int:
    """Absent/unparseable never means zero units -- same rule the Discord
    ingestion side uses (bot/src/parser.py's _parse_quantity): assume 1."""
    if value is None:
        return 1
    if isinstance(value, (int, float)):
        return int(value) or 1
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else 1


_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"]


def _parse_date(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


_ORDER_STATUS_MAP = {
    "success": "success", "successful": "success", "delivered": "success",
    "complete": "success", "completed": "success", "ok": "success",
    "failed": "failed", "fail": "failed", "declined": "failed",
    "denied": "failed", "error": "failed",
    "cancelled": "cancelled", "canceled": "cancelled", "cancel": "cancelled",
    "pending": "pending", "processing": "pending",
}
_ITEM_STATUS_MAP = {
    "in hand": "in_hand", "in_hand": "in_hand", "held": "in_hand", "have": "in_hand",
    "listed": "listed", "for sale": "listed",
    "sold": "sold",
    "returned": "returned", "return": "returned",
    "lost": "lost",
}


def _evaluate_row(
    row: dict,
    mapping: dict[str, Optional[str]],
    mode: str,
    existing_order_numbers: set[str],
) -> dict:
    """
    The single source of truth for "is this row importable, and as what."
    Shared by preview (which just reports the result) and commit (which
    additionally acts on it) -- see the module docstring for why that
    sharing matters.

    Returns a dict always shaped {ok, reason, duplicate, fields}; `fields`
    is populated even when ok=False, so a preview can still show the
    reader what WAS parsed alongside why the row can't be imported.
    """
    product = _extract(row, mapping, "product")
    price = _parse_price(_extract(row, mapping, "price"))
    price_raw = _extract(row, mapping, "price")
    quantity = _parse_quantity(_extract(row, mapping, "quantity"))

    if not product:
        return {"ok": False, "reason": "missing product name", "duplicate": False, "fields": {}}

    if mode == "purchase":
        date_raw = _extract(row, mapping, "order_date")
        order_date = _parse_date(date_raw)
        status_raw = _extract(row, mapping, "status")
        status = _ORDER_STATUS_MAP.get(str(status_raw).strip().lower()) if status_raw else "success"
        order_number = _extract(row, mapping, "order_number")
        order_number = str(order_number).strip() if order_number else None

        if price is None:
            reason = "missing price" if price_raw is None else f"can't read price '{price_raw}'"
            return {"ok": False, "reason": reason, "duplicate": False, "fields": {"product": product}}
        if date_raw is not None and order_date is None:
            return {
                "ok": False, "reason": f"can't read date '{date_raw}'", "duplicate": False,
                "fields": {"product": product, "price": price},
            }
        if status_raw is not None and status is None:
            return {
                "ok": False, "reason": f"can't read status '{status_raw}'", "duplicate": False,
                "fields": {"product": product, "price": price},
            }

        duplicate = bool(order_number) and order_number in existing_order_numbers
        fields = {
            "raw_product_text": product,
            "site": _extract(row, mapping, "site"),
            "category": _extract(row, mapping, "category"),
            "ship_to_label": _extract(row, mapping, "ship_to_label"),
            "order_number": order_number,
            "quantity": quantity,
            "unit_price": (price / quantity) if quantity else price,
            "status": status or "success",
            "purchased_at": order_date.isoformat() if order_date else None,
        }
        return {"ok": True, "reason": None, "duplicate": duplicate, "fields": fields}

    # mode == "unit"
    status_raw = _extract(row, mapping, "status")
    status = _ITEM_STATUS_MAP.get(str(status_raw).strip().lower()) if status_raw else "in_hand"

    if price is None:
        reason = "missing price" if price_raw is None else f"can't read price '{price_raw}'"
        return {"ok": False, "reason": reason, "duplicate": False, "fields": {"product": product}}
    if status_raw is not None and status is None:
        return {
            "ok": False, "reason": f"can't read status '{status_raw}'", "duplicate": False,
            "fields": {"product": product, "price": price},
        }

    fields = {
        "product_text": product,
        "cost_basis": (price / quantity) if quantity else price,
        "status": status or "in_hand",
        "notes": _extract(row, mapping, "notes"),
        "quantity": quantity,  # not a real column -- consumed by commit to spawn N rows
    }
    return {"ok": True, "reason": None, "duplicate": False, "fields": fields}


def _existing_order_numbers(db: Session) -> set[str]:
    rows = (
        db.query(models.Order.order_number)
        .filter(models.Order.order_number.isnot(None))
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _evaluate_all_rows(
    rows: list[dict], mapping: dict[str, Optional[str]], mode: str, db: Session
) -> list[dict]:
    """
    Runs every row through _evaluate_row, with ONE piece of state threaded
    across the whole file: order numbers seen so far. That's what makes
    "two rows in this same spreadsheet share an order number" correctly
    flag the second one as a duplicate too, not just a number that was
    already in the database before the import started. preview and commit
    both call this exact function so they can never disagree about which
    rows are ready, duplicate, or need attention.
    """
    seen_order_numbers = _existing_order_numbers(db)
    results = []
    for row in rows:
        result = _evaluate_row(row, mapping, mode, seen_order_numbers)
        results.append(result)
        if result["ok"] and not result["duplicate"]:
            order_number = result["fields"].get("order_number")
            if order_number:
                seen_order_numbers.add(order_number)
    return results


@router.post("/preview")
async def preview_import(
    file: UploadFile,
    sheet: Optional[str] = Form(default=None),
    mode: str = Form(default="purchase"),
    mapping_json: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    """
    Read-only: never writes anything. Returns detected columns, a
    suggested mapping (or the caller's own mapping, if it's iterating on
    one it already adjusted -- pass mapping_json to re-preview with an
    edited mapping without re-guessing from scratch), sheet names for an
    .xlsx with more than one, and every row's evaluation result so the
    confirm screen can show real per-row status, not just a count.
    """
    if mode not in ("purchase", "unit"):
        raise HTTPException(status_code=400, detail="mode must be 'purchase' or 'unit'")
    fields = _PURCHASE_FIELDS if mode == "purchase" else _UNIT_FIELDS

    content = await file.read()
    headers, rows, sheet_names = _read_rows(file.filename or "", content, sheet)

    mapping = json.loads(mapping_json) if mapping_json else _guess_mapping(headers, fields)
    results = _evaluate_all_rows(rows, mapping, mode, db)

    ready = sum(1 for r in results if r["ok"] and not r["duplicate"])
    duplicates = sum(1 for r in results if r["ok"] and r["duplicate"])
    needs_attention = sum(1 for r in results if not r["ok"])

    return {
        "filename": file.filename,
        "sheet": sheet or (sheet_names[0] if sheet_names else None),
        "sheet_names": sheet_names,
        "columns": headers,
        "mapping": mapping,
        "row_count": len(rows),
        "ready": ready,
        "duplicates": duplicates,
        "needs_attention": needs_attention,
        "rows": [
            {"row_number": i + 2, **r}  # +2: 1-indexed, plus the header row itself
            for i, r in enumerate(results)
        ],
    }


@router.post("/commit")
async def commit_import(
    file: UploadFile,
    sheet: Optional[str] = Form(default=None),
    mode: str = Form(default="purchase"),
    mapping_json: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    The actual write. Every ok=True, non-duplicate row from _evaluate_row
    becomes real rows -- an Order (+ inventory_items if status='success',
    same crud.create_order path Discord ingestion uses) for mode='purchase',
    or `quantity` standalone InventoryItems directly for mode='unit'.

    Creates ONE new `sources` row (type='import') per commit call, never
    reused across separate imports -- see docs/DATA-MODEL.md: each import
    run being its own source is what makes an import reversible (delete
    the source, delete what it created).
    """
    if mode not in ("purchase", "unit"):
        raise HTTPException(status_code=400, detail="mode must be 'purchase' or 'unit'")

    mapping = json.loads(mapping_json)

    content = await file.read()
    headers, rows, sheet_names = _read_rows(file.filename or "", content, sheet)
    if not rows:
        raise HTTPException(status_code=400, detail="No data rows found in that file.")

    user = crud.get_or_create_default_user(db)
    source = models.Source(
        user_id=user.id,
        type="import",
        name=f"Import: {file.filename}",
        config={"filename": file.filename, "imported_at": _now().isoformat(), "mode": mode},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    results = _evaluate_all_rows(rows, mapping, mode, db)
    created_orders = 0
    created_items = 0
    skipped = 0
    duplicates = 0

    for i, (row, result) in enumerate(zip(rows, results)):
        if not result["ok"]:
            skipped += 1
            continue
        if result["duplicate"]:
            duplicates += 1
            continue

        f = result["fields"]
        if mode == "purchase":
            order = models.Order(
                user_id=user.id,
                source_id=source.id,
                external_id=f"import:{source.id}:row{i}",
                status=f["status"],
                raw_product_text=f["raw_product_text"],
                site=f["site"],
                category=f["category"],
                ship_to_label=f["ship_to_label"],
                order_number=f["order_number"],
                quantity=f["quantity"],
                unit_price=f["unit_price"],
                purchased_at=datetime.fromisoformat(f["purchased_at"]) if f["purchased_at"] else None,
                raw_json={"imported_row": {k: str(v) for k, v in row.items()}},
            )
            db.add(order)
            db.flush()  # need order.id before spawning inventory_items
            created_orders += 1

            if f["status"] == "success":
                for unit_index in range(1, f["quantity"] + 1):
                    db.add(
                        models.InventoryItem(
                            user_id=user.id,
                            order_id=order.id,
                            unit_index=unit_index,
                            status="in_hand",
                            cost_basis=f["unit_price"],
                        )
                    )
                    created_items += 1

        else:  # mode == "unit"
            for _ in range(f["quantity"]):
                db.add(
                    models.InventoryItem(
                        user_id=user.id,
                        order_id=None,
                        status=f["status"],
                        product_text=f["product_text"],
                        cost_basis=f["cost_basis"],
                        notes=f["notes"],
                    )
                )
                created_items += 1

    db.commit()

    return {
        "source_id": source.id,
        "created_orders": created_orders,
        "created_inventory_items": created_items,
        "skipped": skipped,
        "duplicates": duplicates,
    }
