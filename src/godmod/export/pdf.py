from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import struct
import zlib

from ..models import ReportBundle
from ..request_options import format_period_label


PAGE_WIDTH = 1191.0
PAGE_HEIGHT = 842.0
LEFT_MARGIN = 24.0
RIGHT_MARGIN = 24.0
TOP_MARGIN = 36.0
BOTTOM_MARGIN = 24.0
TABLE_FONT_SIZE = 6.0
TABLE_HEADER_FONT_SIZE = 6.0
TABLE_CELL_PADDING_X = 2.0
TABLE_CELL_PADDING_Y = 2.0
TABLE_MAX_CELL_LINES = 4

DEFAULT_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)


class PdfRenderError(RuntimeError):
    """Raised when PDF report generation cannot be completed."""


@dataclass(slots=True)
class _PdfLine:
    text: str
    x: float
    y: float
    font_size: float


@dataclass(slots=True)
class _PdfPage:
    lines: list[_PdfLine]
    commands: list[str]


@dataclass(slots=True)
class _PdfFont:
    path: Path
    font_bytes: bytes
    base_name: str
    units_per_em: int
    ascent: int
    descent: int
    cap_height: int
    bbox: tuple[int, int, int, int]
    italic_angle: int
    glyph_widths: list[int]
    cmap: dict[int, int]

    @classmethod
    def load(cls, font_path: str | Path | None = None) -> _PdfFont:
        resolved = _resolve_font_path(font_path)
        data = resolved.read_bytes()
        tables = _ttf_tables(data)

        try:
            head_offset, _ = tables["head"]
            hhea_offset, _ = tables["hhea"]
            maxp_offset, _ = tables["maxp"]
            hmtx_offset, _ = tables["hmtx"]
            cmap_offset, _ = tables["cmap"]
        except KeyError as exc:
            raise PdfRenderError(f"TTF font {resolved} is missing required table {exc}.") from exc

        units_per_em = _u16(data, head_offset + 18)
        bbox = (
            _s16(data, head_offset + 36),
            _s16(data, head_offset + 38),
            _s16(data, head_offset + 40),
            _s16(data, head_offset + 42),
        )
        ascent = _s16(data, hhea_offset + 4)
        descent = _s16(data, hhea_offset + 6)
        number_of_h_metrics = _u16(data, hhea_offset + 34)
        num_glyphs = _u16(data, maxp_offset + 4)
        italic_angle = _parse_italic_angle(data, tables)
        glyph_widths = _parse_hmtx(data, hmtx_offset, number_of_h_metrics, num_glyphs)
        cmap = _parse_cmap(data, cmap_offset)
        if not cmap:
            raise PdfRenderError(f"Unable to read Unicode cmap from {resolved}.")

        return cls(
            path=resolved,
            font_bytes=data,
            base_name=_sanitize_font_name(resolved.stem),
            units_per_em=units_per_em,
            ascent=_scale_metric(ascent, units_per_em),
            descent=_scale_metric(descent, units_per_em),
            cap_height=_scale_metric(ascent, units_per_em),
            bbox=tuple(_scale_metric(value, units_per_em) for value in bbox),
            italic_angle=italic_angle,
            glyph_widths=glyph_widths,
            cmap=cmap,
        )

    def sanitize_text(self, value: str) -> str:
        result: list[str] = []
        for char in value:
            codepoint = ord(char)
            if codepoint > 0xFFFF:
                result.append("?")
                continue
            if codepoint in self.cmap:
                result.append(char)
                continue
            result.append("?")
        return "".join(result)

    def width_1000(self, char: str) -> int:
        glyph_id = self.cmap.get(ord(char), self.cmap.get(ord("?"), 0))
        if glyph_id >= len(self.glyph_widths):
            glyph_id = 0
        return _scale_metric(self.glyph_widths[glyph_id], self.units_per_em)

    def glyph_id(self, char: str) -> int:
        glyph_id = self.cmap.get(ord(char), self.cmap.get(ord("?"), 0))
        if glyph_id >= len(self.glyph_widths):
            return 0
        return glyph_id


class _PdfLayout:
    def __init__(self, font: _PdfFont) -> None:
        self.font = font
        self.pages: list[_PdfPage] = [self._new_page()]
        self.current_y = PAGE_HEIGHT - TOP_MARGIN

    @property
    def current_page(self) -> _PdfPage:
        return self.pages[-1]

    def add_heading(self, text: str, *, font_size: int = 16) -> None:
        self._add_wrapped_text(text, font_size=font_size, gap_after=8.0)

    def add_paragraph(
        self,
        text: str,
        *,
        font_size: int = 11,
        indent: float = 0.0,
        gap_after: float = 4.0,
    ) -> None:
        self._add_wrapped_text(text, font_size=font_size, indent=indent, gap_after=gap_after)

    def add_spacer(self, height: float) -> None:
        self._ensure_space(height)
        self.current_y -= height

    def add_command(self, command: str) -> None:
        self.current_page.commands.append(command)

    def finalize(self) -> list[_PdfPage]:
        total_pages = len(self.pages)
        for index, page in enumerate(self.pages, start=1):
            label = f"Стр. {index}/{total_pages}"
            width = self.measure_text(label, 9)
            page.lines.append(_PdfLine(label, PAGE_WIDTH - RIGHT_MARGIN - width, 12.0, 9))
        return self.pages

    def measure_text(self, text: str, font_size: float) -> float:
        sanitized = self.font.sanitize_text(text)
        return sum(self.font.width_1000(char) for char in sanitized) * font_size / 1000.0

    def _add_wrapped_text(
        self,
        text: str,
        *,
        font_size: int,
        indent: float = 0.0,
        gap_after: float = 0.0,
    ) -> None:
        max_width = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN - indent
        for paragraph in text.splitlines() or [""]:
            normalized = " ".join(paragraph.split())
            if not normalized:
                self._ensure_space(font_size * 1.25)
                self.current_y -= font_size * 1.25
                continue
            lines = _wrap_text(normalized, font_size, max_width, self.measure_text)
            for line in lines:
                line_height = font_size * 1.35
                self._ensure_space(line_height)
                self.current_page.lines.append(
                    _PdfLine(self.font.sanitize_text(line), LEFT_MARGIN + indent, self.current_y, font_size)
                )
                self.current_y -= line_height
        if gap_after:
            self._ensure_space(gap_after)
            self.current_y -= gap_after

    def _ensure_space(self, height: float) -> None:
        if self.current_y - height < BOTTOM_MARGIN:
            self.pages.append(self._new_page())
            self.current_y = PAGE_HEIGHT - TOP_MARGIN

    def _new_page(self) -> _PdfPage:
        return _PdfPage(lines=[], commands=["0.25 w"])


def write_pdf_report(
    path: str | Path,
    bundle: ReportBundle,
    rows: dict[str, list[dict[str, object]]],
    *,
    font_path: str | Path | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    font = _PdfFont.load(font_path or os.environ.get("GODMOD_PDF_FONT_PATH"))
    pages = _build_pages(bundle, rows, font)
    target.write_bytes(_build_pdf(pages, font))
    return target


def _build_pages(
    bundle: ReportBundle,
    rows: dict[str, list[dict[str, object]]],
    font: _PdfFont,
) -> list[_PdfPage]:
    layout = _PdfLayout(font)
    all_accounts = rows.get("all_accounts", [])

    generated_at = (
        str(all_accounts[0].get("Дата сбора", "нет данных"))
        if all_accounts
        else "нет данных"
    )

    layout.add_heading("Godmod PDF-отчёт", font_size=18)
    layout.add_paragraph(f"Дата сбора: {generated_at}", font_size=10, gap_after=2.0)
    layout.add_paragraph(f"Города: {', '.join(bundle.request.cities)}", font_size=10, gap_after=2.0)
    layout.add_paragraph(
        f"Услуги: {', '.join(service.name for service in bundle.request.services)}",
        font_size=10,
        gap_after=2.0,
    )
    layout.add_paragraph(
        f"Период: {format_period_label(bundle.request.period_days)} | Режим: {bundle.request.report_mode}",
        font_size=10,
        gap_after=4.0,
    )
    layout.add_paragraph(
        "PDF дублирует основной лист all_accounts в табличном виде. XLSX остаётся полным основным экспортом.",
        font_size=10,
        gap_after=8.0,
    )

    if not all_accounts:
        layout.add_paragraph("Подходящих аккаунтов в отчёте нет.", font_size=11)
        return layout.finalize()

    headers = list(all_accounts[0].keys())
    _render_table(layout, headers, all_accounts)

    return layout.finalize()


def _build_pdf(pages: list[_PdfPage], font: _PdfFont) -> bytes:
    used_chars = sorted({char for page in pages for line in page.lines for char in line.text})
    if not used_chars:
        used_chars = [" "]

    cid_map: dict[str, tuple[int, int, int]] = {}
    for cid, char in enumerate(used_chars, start=1):
        cid_map[char] = (cid, font.glyph_id(char), font.width_1000(char))

    objects: list[bytes] = []
    page_ids = [3 + index * 2 for index in range(len(pages))]
    content_ids = [page_id + 1 for page_id in page_ids]
    font_id = 3 + len(pages) * 2
    cid_font_id = font_id + 1
    descriptor_id = cid_font_id + 1
    font_file_id = descriptor_id + 1
    to_unicode_id = font_file_id + 1
    cid_map_id = to_unicode_id + 1

    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"2 0 obj\n<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>\nendobj\n".encode("ascii"))

    for page, page_id, content_id in zip(pages, page_ids, content_ids, strict=True):
        objects.append(
            (
                f"{page_id} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.0f} {PAGE_HEIGHT:.0f}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>\n"
                "endobj\n"
            ).encode("ascii")
        )
        objects.append(_stream_object(content_id, _page_content(page, cid_map), compress=True))

    objects.append(
        (
            f"{font_id} 0 obj\n"
            f"<< /Type /Font /Subtype /Type0 /BaseFont /{font.base_name} /Encoding /Identity-H "
            f"/DescendantFonts [{cid_font_id} 0 R] /ToUnicode {to_unicode_id} 0 R >>\n"
            "endobj\n"
        ).encode("ascii")
    )
    widths = " ".join(str(cid_map[char][2]) for char in used_chars)
    objects.append(
        (
            f"{cid_font_id} 0 obj\n"
            f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{font.base_name} "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            f"/FontDescriptor {descriptor_id} 0 R /DW 1000 /W [1 [{widths}]] "
            f"/CIDToGIDMap {cid_map_id} 0 R >>\n"
            "endobj\n"
        ).encode("ascii")
    )
    bbox = " ".join(str(value) for value in font.bbox)
    objects.append(
        (
            f"{descriptor_id} 0 obj\n"
            f"<< /Type /FontDescriptor /FontName /{font.base_name} /Flags 32 "
            f"/FontBBox [{bbox}] /Ascent {font.ascent} /Descent {font.descent} "
            f"/CapHeight {font.cap_height} /ItalicAngle {font.italic_angle} /StemV 80 "
            f"/FontFile2 {font_file_id} 0 R >>\n"
            "endobj\n"
        ).encode("ascii")
    )
    objects.append(
        _stream_object(
            font_file_id,
            font.font_bytes,
            compress=True,
            extra_entries={"Length1": str(len(font.font_bytes))},
        )
    )
    objects.append(_stream_object(to_unicode_id, _to_unicode_cmap(cid_map), compress=True))
    objects.append(_stream_object(cid_map_id, _cid_to_gid_map(cid_map), compress=True))

    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj
    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n".encode("ascii")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode("ascii")
    pdf += (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    return pdf


def _page_content(page: _PdfPage, cid_map: dict[str, tuple[int, int, int]]) -> bytes:
    commands = list(page.commands)
    for line in page.lines:
        encoded = "".join(f"{cid_map[char][0]:04X}" for char in line.text)
        commands.append(
            f"BT /F1 {line.font_size} Tf 1 0 0 1 {line.x:.2f} {line.y:.2f} Tm <{encoded}> Tj ET"
        )
    return "\n".join(commands).encode("ascii")


def _render_table(
    layout: _PdfLayout,
    headers: list[str],
    rows: list[dict[str, object]],
) -> None:
    table_font_size, header_font_size, header_max_lines, table_max_lines = _table_layout_metrics(headers)
    column_widths = _table_column_widths(headers)
    _render_table_header(layout, headers, column_widths, header_font_size=header_font_size, max_lines=header_max_lines)

    for row in rows:
        cell_lines = [
            _table_cell_lines(
                str(row.get(header, "")),
                table_font_size,
                width - TABLE_CELL_PADDING_X * 2,
                layout.measure_text,
                max_lines=table_max_lines,
            )
            for header, width in zip(headers, column_widths, strict=True)
        ]
        row_height = _table_row_height(cell_lines, table_font_size, min_height=12.0)
        if layout.current_y - row_height < BOTTOM_MARGIN:
            layout.pages.append(layout._new_page())
            layout.current_y = PAGE_HEIGHT - TOP_MARGIN
            _render_table_header(layout, headers, column_widths, header_font_size=header_font_size, max_lines=header_max_lines)
        _draw_table_row(layout, column_widths, cell_lines, table_font_size, row_height)


def _render_table_header(
    layout: _PdfLayout,
    headers: list[str],
    column_widths: list[float],
    *,
    header_font_size: float = TABLE_HEADER_FONT_SIZE,
    max_lines: int = 3,
) -> None:
    header_lines = [
        _table_cell_lines(
            header,
            header_font_size,
            width - TABLE_CELL_PADDING_X * 2,
            layout.measure_text,
            max_lines=max_lines,
        )
        for header, width in zip(headers, column_widths, strict=True)
    ]
    row_height = _table_row_height(header_lines, header_font_size, min_height=16.0)
    if layout.current_y - row_height < BOTTOM_MARGIN:
        layout.pages.append(layout._new_page())
        layout.current_y = PAGE_HEIGHT - TOP_MARGIN
    _draw_table_row(layout, column_widths, header_lines, header_font_size, row_height)


def _draw_table_row(
    layout: _PdfLayout,
    column_widths: list[float],
    cell_lines: list[list[str]],
    font_size: float,
    row_height: float,
) -> None:
    row_top = layout.current_y
    row_bottom = row_top - row_height
    x = LEFT_MARGIN

    for width, lines in zip(column_widths, cell_lines, strict=True):
        layout.add_command(f"{x:.2f} {row_bottom:.2f} {width:.2f} {row_height:.2f} re S")
        text_y = row_top - TABLE_CELL_PADDING_Y - font_size
        for index, line in enumerate(lines):
            layout.current_page.lines.append(
                _PdfLine(
                    layout.font.sanitize_text(line),
                    x + TABLE_CELL_PADDING_X,
                    text_y - index * (font_size * 1.15),
                    font_size,
                )
            )
        x += width

    layout.current_y = row_bottom


def _table_column_widths(headers: list[str]) -> list[float]:
    weights = {
        "id": 60.0,
        "Название": 120.0,
        "Тип": 75.0,
        "Ссылка": 100.0,
        "Город / локация": 85.0,
        "Город из API": 70.0,
        "Адрес (если есть)": 95.0,
        "Координаты": 80.0,
        "Категории": 85.0,
        "Рейтинг / отзывы": 70.0,
        "Часы работы": 85.0,
        "Описание деятельности": 140.0,
        "Ключевые слова услуг": 95.0,
        "Подписчики": 55.0,
        "Активность (постинг)": 75.0,
        "Постов за 30 дней": 55.0,
        "Средние лайки": 55.0,
        "Средние комментарии": 60.0,
        "Средние репосты": 55.0,
        "ER, %": 45.0,
        "Коммерческие маркеры": 90.0,
        "Сотрудники": 70.0,
        "Телефон": 75.0,
        "Контакты администратора": 110.0,
        "Ссылка для записи": 105.0,
        "Цены / прайс": 90.0,
        "Официальные реквизиты": 90.0,
        "Служебные поля 2GIS": 90.0,
        "Сотрудников (2GIS)": 75.0,
        "Дата сбора": 70.0,
        "Примечание": 125.0,
    }
    raw_widths = [weights.get(header, 80.0) for header in headers]
    available_width = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
    scale = available_width / sum(raw_widths)
    return [round(width * scale, 2) for width in raw_widths]


def _table_layout_metrics(headers: list[str]) -> tuple[float, float, int, int]:
    if len(headers) >= 26:
        return 5.2, 4.8, 5, 4
    if len(headers) >= 22:
        return 5.6, 5.2, 4, 4
    return TABLE_FONT_SIZE, TABLE_HEADER_FONT_SIZE, 3, TABLE_MAX_CELL_LINES


def _table_cell_lines(
    value: str,
    font_size: float,
    max_width: float,
    measure: callable,
    *,
    max_lines: int,
) -> list[str]:
    normalized = " ".join(value.split())
    if not normalized:
        return [""]
    wrapped = _wrap_text(normalized, font_size, max_width, measure)
    if len(wrapped) <= max_lines:
        return wrapped
    trimmed = wrapped[:max_lines]
    last = trimmed[-1].rstrip()
    if len(last) > 1:
        trimmed[-1] = f"{last[:-1].rstrip()}…"
    else:
        trimmed[-1] = "…"
    return trimmed


def _table_row_height(
    cell_lines: list[list[str]],
    font_size: float,
    *,
    min_height: float,
) -> float:
    max_line_count = max((len(lines) for lines in cell_lines), default=1)
    content_height = max_line_count * (font_size * 1.15)
    return max(min_height, content_height + TABLE_CELL_PADDING_Y * 2 + 2.0)


def _to_unicode_cmap(cid_map: dict[str, tuple[int, int, int]]) -> bytes:
    ordered = sorted(((cid, char) for char, (cid, _, _) in cid_map.items()), key=lambda item: item[0])
    chunks = [ordered[index : index + 100] for index in range(0, len(ordered), 100)]
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0001> <FFFF>",
        "endcodespacerange",
    ]
    for chunk in chunks:
        lines.append(f"{len(chunk)} beginbfchar")
        for cid, char in chunk:
            lines.append(f"<{cid:04X}> <{ord(char):04X}>")
        lines.append("endbfchar")
    lines.extend(
        [
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ]
    )
    return "\n".join(lines).encode("ascii")


def _cid_to_gid_map(cid_map: dict[str, tuple[int, int, int]]) -> bytes:
    max_cid = max(cid for cid, _, _ in cid_map.values())
    mapping = bytearray((max_cid + 1) * 2)
    for cid, glyph_id, _ in cid_map.values():
        mapping[cid * 2 : cid * 2 + 2] = glyph_id.to_bytes(2, "big")
    return bytes(mapping)


def _stream_object(
    object_id: int,
    payload: bytes,
    *,
    compress: bool = False,
    extra_entries: dict[str, str] | None = None,
) -> bytes:
    body = zlib.compress(payload) if compress else payload
    entries = {"Length": str(len(body))}
    if compress:
        entries["Filter"] = "/FlateDecode"
    if extra_entries:
        entries.update(extra_entries)
    dict_body = " ".join(f"/{key} {value}" for key, value in entries.items())
    return (
        f"{object_id} 0 obj\n<< {dict_body} >>\nstream\n".encode("ascii")
        + body
        + b"\nendstream\nendobj\n"
    )


def _wrap_text(
    text: str,
    font_size: float,
    max_width: float,
    measure: callable,
) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if candidate and measure(candidate, font_size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if measure(word, font_size) <= max_width:
            current = word
            continue
        lines.extend(_break_long_token(word, font_size, max_width, measure))
    if current:
        lines.append(current)
    return lines or [text]


def _break_long_token(
    token: str,
    font_size: float,
    max_width: float,
    measure: callable,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if candidate and measure(candidate, font_size) <= max_width:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = char
    if current:
        chunks.append(current)
    return chunks


def _resolve_font_path(font_path: str | Path | None) -> Path:
    candidates: list[Path] = []
    if font_path:
        candidates.append(Path(font_path))
    candidates.extend(Path(item) for item in DEFAULT_FONT_PATHS)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = ", ".join(str(candidate) for candidate in candidates)
    raise PdfRenderError(
        "PDF export requires a Unicode TTF font. "
        "Set GODMOD_PDF_FONT_PATH or install DejaVu Sans. "
        f"Tried: {tried}"
    )


def _sanitize_font_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value)
    return f"Godmod{cleaned or 'ReportFont'}"


def _scale_metric(value: int, units_per_em: int) -> int:
    return round(value * 1000 / units_per_em)


def _ttf_tables(data: bytes) -> dict[str, tuple[int, int]]:
    table_count = _u16(data, 4)
    offset = 12
    tables: dict[str, tuple[int, int]] = {}
    for _ in range(table_count):
        tag = data[offset : offset + 4].decode("ascii", errors="replace")
        tables[tag] = (_u32(data, offset + 8), _u32(data, offset + 12))
        offset += 16
    return tables


def _parse_hmtx(data: bytes, offset: int, number_of_h_metrics: int, num_glyphs: int) -> list[int]:
    widths: list[int] = []
    last_advance = 0
    for glyph_id in range(num_glyphs):
        if glyph_id < number_of_h_metrics:
            last_advance = _u16(data, offset + glyph_id * 4)
        widths.append(last_advance)
    return widths


def _parse_italic_angle(data: bytes, tables: dict[str, tuple[int, int]]) -> int:
    post_table = tables.get("post")
    if post_table is None:
        return 0
    offset, _ = post_table
    return round(_s32(data, offset + 4) / 65536)


def _parse_cmap(data: bytes, offset: int) -> dict[int, int]:
    subtable_count = _u16(data, offset + 2)
    chosen: tuple[int, int, int] | None = None
    priorities = {
        (3, 10, 12): 5,
        (0, 4, 12): 4,
        (3, 1, 4): 3,
        (0, 3, 4): 2,
        (0, 4, 4): 1,
    }
    for index in range(subtable_count):
        platform_id = _u16(data, offset + 4 + index * 8)
        encoding_id = _u16(data, offset + 6 + index * 8)
        subtable_offset = _u32(data, offset + 8 + index * 8)
        format_id = _u16(data, offset + subtable_offset)
        priority = priorities.get((platform_id, encoding_id, format_id), 0)
        if priority and (chosen is None or priority > chosen[0]):
            chosen = (priority, offset + subtable_offset, format_id)
    if chosen is None:
        return {}
    _, subtable_offset, format_id = chosen
    if format_id == 12:
        return _parse_cmap_format_12(data, subtable_offset)
    if format_id == 4:
        return _parse_cmap_format_4(data, subtable_offset)
    return {}


def _parse_cmap_format_12(data: bytes, offset: int) -> dict[int, int]:
    group_count = _u32(data, offset + 12)
    cursor = offset + 16
    mapping: dict[int, int] = {}
    for _ in range(group_count):
        start = _u32(data, cursor)
        end = _u32(data, cursor + 4)
        start_glyph_id = _u32(data, cursor + 8)
        cursor += 12
        for codepoint in range(start, end + 1):
            mapping[codepoint] = start_glyph_id + (codepoint - start)
    return mapping


def _parse_cmap_format_4(data: bytes, offset: int) -> dict[int, int]:
    seg_count = _u16(data, offset + 6) // 2
    end_codes_offset = offset + 14
    start_codes_offset = end_codes_offset + 2 * seg_count + 2
    id_deltas_offset = start_codes_offset + 2 * seg_count
    id_range_offsets_offset = id_deltas_offset + 2 * seg_count
    mapping: dict[int, int] = {}

    for index in range(seg_count):
        end_code = _u16(data, end_codes_offset + 2 * index)
        start_code = _u16(data, start_codes_offset + 2 * index)
        id_delta = _s16(data, id_deltas_offset + 2 * index)
        id_range_offset = _u16(data, id_range_offsets_offset + 2 * index)
        if start_code == 0xFFFF and end_code == 0xFFFF:
            continue
        for codepoint in range(start_code, end_code + 1):
            if id_range_offset == 0:
                glyph_id = (codepoint + id_delta) & 0xFFFF
            else:
                glyph_offset = id_range_offsets_offset + 2 * index + id_range_offset + 2 * (codepoint - start_code)
                glyph_id = _u16(data, glyph_offset)
                if glyph_id:
                    glyph_id = (glyph_id + id_delta) & 0xFFFF
            if glyph_id:
                mapping[codepoint] = glyph_id
    return mapping


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _s16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _s32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">i", data, offset)[0]
