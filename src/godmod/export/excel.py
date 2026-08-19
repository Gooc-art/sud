from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


@dataclass(slots=True)
class SheetSpec:
    name: str
    rows: list[dict[str, object]]
    freeze_header: bool = False
    auto_filter: bool = False
    column_widths: dict[str, float] | None = None


def write_workbook(path: str | Path, sheets: list[SheetSpec]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    prepared = [_prepare_sheet(sheet, index + 1) for index, sheet in enumerate(sheets)]

    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(prepared)))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("xl/workbook.xml", _workbook(prepared))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(prepared)))
        archive.writestr("xl/styles.xml", _styles())
        for sheet in prepared:
            archive.writestr(f"xl/worksheets/sheet{sheet['id']}.xml", sheet["xml"])
    return target


def _prepare_sheet(sheet: SheetSpec, sheet_id: int) -> dict[str, object]:
    columns = list(sheet.rows[0].keys()) if sheet.rows else []
    data_rows = [columns] + [[row.get(column, "") for column in columns] for row in sheet.rows]
    resolved_column_widths = _resolve_column_widths(columns, sheet.column_widths)
    return {
        "id": sheet_id,
        "name": _sanitize_sheet_name(sheet.name, sheet_id),
        "xml": _sheet_xml(
            data_rows,
            freeze_header=sheet.freeze_header,
            auto_filter=sheet.auto_filter,
            column_widths=resolved_column_widths,
        ),
    }


def _sanitize_sheet_name(value: str, index: int) -> str:
    sanitized = value.translate(str.maketrans({char: "_" for char in r'[]:*?/\\'})).strip()
    if not sanitized:
        sanitized = f"Sheet{index}"
    return sanitized[:31]


def _sheet_xml(
    rows: list[list[object]],
    *,
    freeze_header: bool = False,
    auto_filter: bool = False,
    column_widths: list[float] | None = None,
) -> str:
    row_count = len(rows)
    column_count = len(rows[0]) if rows else 0
    dimension_ref = _sheet_dimension_ref(row_count, column_count)
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        f'<dimension ref="{dimension_ref}"/>',
    ]
    if freeze_header:
        parts.append(
            '<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
            "</sheetView></sheetViews>"
        )
    if column_widths:
        parts.append("<cols>")
        for index, width in enumerate(column_widths, start=1):
            parts.append(f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>')
        parts.append("</cols>")
    parts.append("<sheetData>")
    for row_index, row in enumerate(rows, start=1):
        parts.append(f'<row r="{row_index}">')
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{_column_name(column_index)}{row_index}"
            parts.append(_cell_xml(cell_ref, value))
        parts.append("</row>")
    parts.append("</sheetData>")
    if auto_filter and row_count > 0 and column_count > 0:
        parts.append(f'<autoFilter ref="A1:{_column_name(column_count)}{row_count}"/>')
    parts.append("</worksheet>")
    return "".join(parts)


def _cell_xml(cell_ref: str, value: object) -> str:
    if value is None or value == "":
        return f'<c r="{cell_ref}" t="inlineStr"><is><t></t></is></c>'
    if isinstance(value, bool):
        numeric = "1" if value else "0"
        return f'<c r="{cell_ref}" t="b"><v>{numeric}</v></c>'
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return f'<c r="{cell_ref}"><v>{value}</v></c>'
    if isinstance(value, (date, datetime)):
        text = escape(value.isoformat())
        return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'
    text = escape(str(value))
    return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _column_name(index: int) -> str:
    result = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _sheet_dimension_ref(row_count: int, column_count: int) -> str:
    if row_count <= 0 or column_count <= 0:
        return "A1"
    return f"A1:{_column_name(column_count)}{row_count}"


def _resolve_column_widths(columns: list[str], configured_widths: dict[str, float] | None) -> list[float] | None:
    if not columns or not configured_widths:
        return None
    return [configured_widths.get(column, 12.0) for column in columns]


def _content_types(sheet_count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{sheet_id}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for sheet_id in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{overrides}"
        "</Types>"
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook(sheets: list[dict[str, object]]) -> str:
    sheet_xml = "".join(
        f'<sheet name="{escape(sheet["name"])}" sheetId="{sheet["id"]}" r:id="rId{sheet["id"]}"/>'
        for sheet in sheets
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_xml}</sheets>"
        "</workbook>"
    )


def _workbook_rels(sheet_count: int) -> str:
    sheet_rels = "".join(
        f'<Relationship Id="rId{sheet_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{sheet_id}.xml"/>'
        for sheet_id in range(1, sheet_count + 1)
    )
    styles_id = sheet_count + 1
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{sheet_rels}"
        f'<Relationship Id="rId{styles_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="1"><xf xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
