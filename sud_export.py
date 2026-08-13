#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape


COURTS = {
    "oblsud--ynao.sudrf.ru": "Суд ЯНАО",
    "salehardsky--ynao.sudrf.ru": "Салехардский городской суд",
    "noyabrsky--ynao.sudrf.ru": "Ноябрьский городской суд",
    "nadymsky--ynao.sudrf.ru": "Надымский городской суд",
    "novourengoysky--ynao.sudrf.ru": "Новый Уренгойский городской суд",
    "muravlenkovsky--ynao.sudrf.ru": "Муравленковский городской суд",
    "gubkinskiy--ynao.sudrf.ru": "Губкинский районный суд",
    "purovsky--ynao.sudrf.ru": "Пуровский районный суд",
    "tazovsky--ynao.sudrf.ru": "Тазовский районный суд",
    "yamalsky--ynao.sudrf.ru": "Ямальский районный суд",
    "krasnoselkupsky--ynao.sudrf.ru": "Красноселькупский районный суд",
    "shuryshkarsky--ynao.sudrf.ru": "Шурышкарский районный суд",
    "labytnangsky.ynao.sudrf.ru": "Лабытнангский городской суд",
}

HEADERS = [
    "Группа представителя",
    "Кол-во дел у представителя",
    "Суд",
    "Дата заседания",
    "Время",
    "Номер дела",
    "Категория / причина",
    "Судья",
    "Стороны",
    "Адвокаты / представители",
    "Результат / статус",
    "Ссылка на карточку",
    "Статус проверки",
]


@dataclass
class Row:
    court: str
    hearing_date: str
    time: str
    case_number: str
    info: str
    judge: str
    parties: str
    lawyers: str
    result: str
    url: str
    check: str

    def cells(self) -> list[str]:
        return [
            "",
            "",
            self.court,
            self.hearing_date,
            self.time,
            self.case_number,
            self.info,
            self.judge,
            self.parties,
            self.lawyers,
            self.result,
            self.url,
            self.check,
        ]


def lawyer_key(row: Row) -> str:
    if not row.lawyers:
        return "Без представителя"
    first = row.lawyers.split(";")[0].strip()
    return first.split(":", 1)[1].strip() if ":" in first else first


def is_tax_party(row: Row) -> bool:
    for party in row.parties.split(";"):
        if re.search(r"\b[уи]?фнс\b|федеральн\w+ налогов\w+ служб\w+|налогов\w+ инспекц", party, flags=re.I):
            return True
    return False


def sort_by_lawyer(rows: list[Row]) -> list[list[str]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = lawyer_key(row)
        counts[key] = counts.get(key, 0) + 1

    def key(row: Row):
        group = lawyer_key(row)
        no_lawyer = group == "Без представителя"
        return (no_lawyer, -counts[group], group, row.hearing_date, row.time, row.case_number)

    table_rows = []
    for row in sorted(rows, key=key):
        cells = row.cells()
        group = lawyer_key(row)
        cells[0] = group
        cells[1] = str(counts[group])
        table_rows.append(cells)
    return table_rows


def clean(text: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = html.unescape(re.sub(r"<br\s*/?>", "\n", text, flags=re.I))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).replace("\xa0", " ").strip()


def iter_dates(start: date, end: date):
    while start <= end:
        yield start
        start += timedelta(days=1)


def read_url(url: str, cache_path: Path, refresh: bool = False, timeout: int = 12) -> str:
    if cache_path.exists() and not refresh:
        text = cache_path.read_text(encoding="utf-8", errors="replace")
        validate_page(text, url)
        return text
    result = subprocess.run(
        ["curl", "-L", "-f", "-sS", "--max-time", str(timeout), "-A", "Mozilla/5.0 sud-export/0.1", url],
        capture_output=True,
        timeout=timeout + 2,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or f"curl failed: {result.returncode}")
    raw = result.stdout
    text = raw.decode("utf-8", errors="replace")
    if text.count("�") > 10:
        text = raw.decode("windows-1251", errors="replace")
    validate_page(text, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def validate_page(text: str, url: str) -> None:
    if "Bad Gateway" in text:
        raise RuntimeError(f"bad gateway: {url}")


def schedule_url(host: str, day: date) -> str:
    return f"https://{host}/modules.php?name=sud_delo&srv_num=1&H_date={day:%d.%m.%Y}"


def absolutize(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(href))


def parse_schedule(page: str, base_url: str, court: str, day: date) -> list[Row]:
    rows: list[Row] = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.I | re.S):
        cols = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.I | re.S)
        if len(cols) < 6:
            continue
        case_link = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', cols[1], flags=re.I | re.S)
        case_number = clean(case_link.group(2) if case_link else cols[1])
        if not case_number or case_number.lower() in {"номер дела", "дело"}:
            continue
        url = absolutize(base_url, case_link.group(1)) if case_link else ""
        rows.append(
            Row(
                court=court,
                hearing_date=day.isoformat(),
                time=clean(cols[2]),
                case_number=case_number,
                info=clean(cols[4]),
                judge=clean(cols[5]),
                parties="",
                lawyers="",
                result=clean(cols[6]) if len(cols) > 6 else "",
                url=url,
                check="need_case" if url else "no_case_url",
            )
        )
    return rows


def parse_case(page: str) -> tuple[str, str, str]:
    block_match = re.search(r"<div\b[^>]*id=['\"]cont3['\"][^>]*>(.*?)</div>", page, flags=re.I | re.S)
    if block_match:
        pairs = []
        lawyers = []
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", block_match.group(1), flags=re.I | re.S):
            cols = [clean(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.I | re.S)]
            if len(cols) < 2 or "Вид лица" in cols[0]:
                continue
            role, name = cols[0], cols[1]
            if not role or not name:
                continue
            item = f"{role}: {name}"
            pairs.append(item)
            if re.search(r"адвокат|представ", role, flags=re.I):
                lawyers.append(item)
        parties = "; ".join(pairs)
        if parties:
            return parties[:1000], "; ".join(sorted(set(lawyers))), "ok" if lawyers else "no_lawyer"

    text = clean(page)
    start = re.search(r"СТОРОНЫ(?:\s+ПО\s+ДЕЛУ)?", text, flags=re.I)
    if not start:
        return "", "", "no_parties"
    tail = text[start.end() :]
    stop = re.search(r"\b(ДВИЖЕНИЕ ДЕЛА|СУДЕБНЫЕ АКТЫ|ОБЖАЛОВАНИЕ|ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ)\b", tail, flags=re.I)
    parties = tail[: stop.start()] if stop else tail[:4000]
    parties = re.sub(r"\s+", " ", parties).strip(" -|")
    lawyers = sorted(set(re.findall(r"((?:Защитник \(адвокат\)|адвокат|представитель)[^;|]{0,160})", parties, flags=re.I)))
    return parties[:1000], "; ".join(lawyers), "ok" if lawyers else "no_lawyer"


def collect(
    start: date,
    end: date,
    outdir: Path,
    refresh: bool = False,
    courts: set[str] | None = None,
    timeout: int = 12,
    max_cases: int | None = None,
) -> tuple[list[Row], list[list[str]]]:
    rows: list[Row] = []
    log: list[list[str]] = []
    for host, court in COURTS.items():
        if courts and host not in courts:
            continue
        for day in iter_dates(start, end):
            url = schedule_url(host, day)
            try:
                page = read_url(url, outdir / "cache" / "schedules" / host / f"{day}.html", refresh, timeout)
                day_rows = parse_schedule(page, url, court, day)
            except Exception as exc:
                log.append([court, day.isoformat(), url, type(exc).__name__, str(exc)])
                continue
            for row in day_rows:
                if max_cases is not None and len(rows) >= max_cases:
                    rows.append(row)
                    continue
                if row.url:
                    try:
                        key = re.sub(r"\W+", "_", row.url)[-180:]
                        case_page = read_url(row.url, outdir / "cache" / "cases" / f"{key}.html", refresh, timeout)
                        row.parties, row.lawyers, row.check = parse_case(case_page)
                    except Exception as exc:
                        row.check = "case_error"
                        log.append([court, day.isoformat(), row.url, type(exc).__name__, str(exc)])
                rows.append(row)
    return rows, log


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)


def col_name(n: int) -> str:
    name = ""
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def write_xlsx(path: Path, rows: list[list[str]], extra_sheets: list[tuple[str, list[list[str]]]] | None = None) -> None:
    widths = [28, 12, 28, 13, 24, 45, 24, 90, 28, 90, 90, 28, 55, 16]

    def sheet_xml(sheet_rows: list[list[str]]) -> str:
        row_xmls = []
        for r, row in enumerate(sheet_rows, 1):
            cells = []
            for c, value in enumerate(row, 1):
                ref = f"{col_name(c)}{r}"
                style = 2 if r == 1 else 1
                cells.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{escape(value or "")}</t></is></c>')
            height = ' ht="36" customHeight="1"' if r == 1 else ' ht="54" customHeight="1"'
            row_xmls.append(f'<row r="{r}"{height}>{"".join(cells)}</row>')
        cols = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
        last_ref = f"{col_name(len(HEADERS))}{len(sheet_rows)}"
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="54"/><cols>{cols}</cols><sheetData>{''.join(row_xmls)}</sheetData>
<autoFilter ref="A1:{last_ref}"/><pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
</worksheet>'''

    sheets = [("Report", rows), *(extra_sheets or [])]
    workbook_sheets = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
    workbook_rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    content_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    styles = '''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyAlignment="1" applyFill="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", f'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{content_overrides}</Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{workbook_sheets}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{workbook_rels}<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", styles)
        for i, (_, sheet_rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(sheet_rows))


def write_html(path: Path, rows: list[list[str]]) -> None:
    trs = []
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        cells = "".join(f"<{tag}>{escape(value or '')}</{tag}>" for value in row)
        trs.append(f"<tr>{cells}</tr>")
    path.write_text(
        """<!doctype html><meta charset="utf-8"><style>
body{font-family:Arial,sans-serif;font-size:10px} table{border-collapse:collapse;width:100%}
th,td{border:1px solid #999;padding:4px;vertical-align:top} th{background:#eee}
@page{size:A4 landscape;margin:8mm}
</style><table>"""
        + "".join(trs)
        + "</table>",
        encoding="utf-8",
    )


def pdf_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, rows: list[list[str]], html_path: Path | None = None) -> None:
    if html_path:
        if shutil.which("libreoffice"):
            subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(path.parent), str(html_path)], check=True, timeout=180)
            converted = path.parent / f"{html_path.stem}.pdf"
            if converted != path and converted.exists():
                converted.replace(path)
            if path.exists():
                return
        if shutil.which("wkhtmltopdf"):
            subprocess.run(["wkhtmltopdf", "--orientation", "Landscape", str(html_path), str(path)], check=True, timeout=180)
            return
        browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
        if browser:
            subprocess.run([browser, "--headless", "--disable-gpu", f"--print-to-pdf={path}", str(html_path)], check=True, timeout=180)
            return
    lines = [" | ".join(row[:8]) for row in rows[:200]]
    content = ["BT /F1 8 Tf 40 800 Td"]
    for line in lines:
        for part in textwrap.wrap(line, width=135)[:3]:
            content.append(f"({pdf_text(part)}) Tj 0 -10 Td")
        content.append("0 -4 Td")
    content.append("ET")
    stream = "\n".join(content).encode("cp1251", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    data += f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--outdir", default="output")
    p.add_argument("--court", action="append", choices=sorted(COURTS), help="limit to a court host; can be repeated")
    p.add_argument("--max-cases", type=int, help="stop enriching after this many rows; useful for smoke checks")
    p.add_argument("--sort-by-lawyer", action="store_true")
    p.add_argument("--timeout", type=int, default=12)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args(argv)
    start = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    end = datetime.strptime(args.date_to, "%Y-%m-%d").date()
    outdir = Path(args.outdir)
    rows, log = collect(start, end, outdir, args.refresh, set(args.court or []), args.timeout, args.max_cases)
    table = [HEADERS] + (sort_by_lawyer(rows) if args.sort_by_lawyer else [row.cells() for row in rows])
    tax_table = [HEADERS] + [row.cells() for row in rows if is_tax_party(row)]
    write_xlsx(outdir / "report.xlsx", table, [("ФНС участвует", tax_table)])
    html_path = outdir / "report.html"
    write_html(html_path, table)
    write_pdf(outdir / "report.pdf", table, html_path)
    write_csv(outdir / "report.csv", table)
    write_csv(outdir / "run_log.csv", [["Суд", "Дата", "URL", "Ошибка", "Детали"], *log])
    print(f"rows={len(rows)} xlsx={outdir / 'report.xlsx'} pdf={outdir / 'report.pdf'} log={outdir / 'run_log.csv'}")
    return 2 if not rows and log else 0


if __name__ == "__main__":
    raise SystemExit(main())
