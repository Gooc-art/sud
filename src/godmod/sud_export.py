from __future__ import annotations

import argparse
import csv
import html
import re
import shutil
import subprocess
import textwrap
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    parties: str = ""
    lawyers: str = ""
    result: str = ""
    url: str = ""
    check: str = ""

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


def clean(text: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = html.unescape(re.sub(r"<br\s*/?>", "\n", text, flags=re.I))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).replace("\xa0", " ").strip()


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def iter_dates(start: date, end: date):
    while start <= end:
        yield start
        start += timedelta(days=1)


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
        rows.append(
            Row(
                court=court,
                hearing_date=day.isoformat(),
                time=clean(cols[2]),
                case_number=case_number,
                info=clean(cols[4]),
                judge=clean(cols[5]),
                result=clean(cols[6]) if len(cols) > 6 else "",
                url=absolutize(base_url, case_link.group(1)) if case_link else "",
                check="need_case" if case_link else "no_case_url",
            )
        )
    return rows


def parse_case(page: str) -> tuple[str, str, str]:
    block = re.search(r"<div\b[^>]*id=['\"]cont3['\"][^>]*>(.*?)</div>", page, flags=re.I | re.S)
    if block:
        parties: list[str] = []
        lawyers: list[str] = []
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", block.group(1), flags=re.I | re.S):
            cols = [clean(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.I | re.S)]
            if len(cols) < 2 or "Вид лица" in cols[0]:
                continue
            item = f"{cols[0]}: {cols[1]}"
            parties.append(item)
            if re.search(r"адвокат|представ", cols[0], flags=re.I):
                lawyers.append(item)
        if parties:
            return "; ".join(parties)[:1000], "; ".join(sorted(set(lawyers))), "ok" if lawyers else "no_lawyer"

    text = clean(page)
    start = re.search(r"СТОРОНЫ(?:\s+ПО\s+ДЕЛУ)?", text, flags=re.I)
    if not start:
        return "", "", "no_parties"
    tail = text[start.end() :]
    stop = re.search(r"\b(ДВИЖЕНИЕ ДЕЛА|СУДЕБНЫЕ АКТЫ|ОБЖАЛОВАНИЕ|ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ)\b", tail, flags=re.I)
    parties = re.sub(r"\s+", " ", (tail[: stop.start()] if stop else tail[:4000])).strip(" -|")
    lawyers = sorted(set(re.findall(r"((?:Защитник \(адвокат\)|адвокат|представитель)[^;|]{0,160})", parties, flags=re.I)))
    return parties[:1000], "; ".join(lawyers), "ok" if lawyers else "no_lawyer"


def validate_page(text: str, url: str) -> None:
    if "Bad Gateway" in text:
        raise RuntimeError(f"bad gateway: {url}")


def read_url(url: str, cache_path: Path, refresh: bool = False, timeout: int = 30) -> str:
    if cache_path.exists() and not refresh:
        text = cache_path.read_text(encoding="utf-8", errors="replace")
        validate_page(text, url)
        return text
    try:
        raw = _curl_url(url, timeout)
    except Exception:
        fallback = latest_shared_cache(cache_path)
        if fallback is None or refresh:
            raise
        text = fallback.read_text(encoding="utf-8", errors="replace")
        validate_page(text, url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        return text
    text = raw.decode("utf-8", errors="replace")
    if text.count("�") > 10:
        text = raw.decode("windows-1251", errors="replace")
    validate_page(text, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def _curl_url(url: str, timeout: int) -> bytes:
    result = subprocess.run(
        ["curl", "-L", "-f", "-sS", "--max-time", str(timeout), "-A", "Mozilla/5.0 godmod-sud-export/0.1", url],
        capture_output=True,
        timeout=timeout + 2,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or f"curl failed: {result.returncode}")
    return result.stdout


def latest_shared_cache(cache_path: Path) -> Path | None:
    try:
        cache_root = cache_path.parents[2]
        outdir = cache_path.parents[3]
        relative = cache_path.relative_to(cache_root)
    except (IndexError, ValueError):
        return None
    sud_root = outdir.parent
    if not sud_root.exists():
        return None
    candidates = [
        candidate
        for sibling in sud_root.iterdir()
        if sibling.is_dir() and sibling != outdir
        for candidate in [sibling / "cache" / relative]
        if candidate.exists()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def lawyer_key(row: Row) -> str:
    if not row.lawyers:
        return "Без представителя"
    first = row.lawyers.split(";")[0].strip()
    return first.split(":", 1)[1].strip() if ":" in first else first


def sort_by_lawyer(rows: list[Row]) -> list[list[str]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = lawyer_key(row)
        counts[key] = counts.get(key, 0) + 1
    table = []
    for row in sorted(rows, key=lambda r: (lawyer_key(r) == "Без представителя", -counts[lawyer_key(r)], lawyer_key(r), r.hearing_date, r.time, r.case_number)):
        cells = row.cells()
        cells[0] = lawyer_key(row)
        cells[1] = str(counts[lawyer_key(row)])
        table.append(cells)
    return table


def row_matches_fns_yanao(row: Row) -> bool:
    text = " ".join(
        [
            row.court,
            row.hearing_date,
            row.time,
            row.case_number,
            row.info,
            row.judge,
            row.parties,
            row.lawyers,
            row.result,
            row.url,
        ]
    ).casefold().replace("ё", "е")
    patterns = [
        r"\b(?:уфнс|ифнс|мифнс|фнс)\b.{0,80}\bянао\b",
        r"\bянао\b.{0,80}\b(?:уфнс|ифнс|мифнс|фнс)\b",
        r"инспекц\w*\s+федеральн\w*\s+налогов\w*\s+служб\w*.{0,120}(?:янао|ямало[\s-]+ненецк\w*)",
        r"управлен\w*\s+федеральн\w*\s+налогов\w*\s+служб\w*.{0,120}ямало[\s-]+ненецк\w*",
        r"федеральн\w*\s+налогов\w*\s+служб\w*.{0,120}ямало[\s-]+ненецк\w*",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def is_tax_party(row: Row) -> bool:
    return row_matches_fns_yanao(row)


def selected_courts(court: str | list[str] | None) -> dict[str, str]:
    if not court:
        return COURTS
    wanted = [court] if isinstance(court, str) else court
    selected: dict[str, str] = {}
    for value in wanted:
        matches = [host for host, name in COURTS.items() if value == host or value.casefold() == name.casefold()]
        if not matches:
            raise ValueError(f"unknown court: {value}")
        selected[matches[0]] = COURTS[matches[0]]
    return selected


def collect(
    date_from: str | date,
    date_to: str | date,
    outdir: Path,
    court: str | list[str] | None = None,
    refresh: bool = False,
    timeout: int = 30,
    workers: int = 6,
) -> tuple[list[Row], list[list[str]]]:
    start, end = parse_date(date_from), parse_date(date_to)
    if start > end:
        raise ValueError("date_from must be <= date_to")
    rows: list[Row] = []
    log: list[list[str]] = []
    workers = max(1, workers)
    tasks = [
        (host, court_name, day, schedule_url(host, day))
        for host, court_name in selected_courts(court).items()
        for day in iter_dates(start, end)
    ]

    def fetch_schedule(task: tuple[str, str, date, str]) -> tuple[list[Row], list[str] | None]:
        host, court_name, day, url = task
        try:
            page = read_url(url, outdir / "cache" / "schedules" / host / f"{day}.html", refresh, timeout)
            return parse_schedule(page, url, court_name, day), None
        except Exception as exc:
            return [], [court_name, day.isoformat(), url, type(exc).__name__, str(exc)]

    if workers == 1 or len(tasks) <= 1:
        schedule_results = [fetch_schedule(task) for task in tasks]
    else:
        schedule_results = [None] * len(tasks)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_schedule, task): i for i, task in enumerate(tasks)}
            for future in as_completed(futures):
                schedule_results[futures[future]] = future.result()

    for day_rows, error in schedule_results:
        rows.extend(day_rows)
        if error:
            log.append(error)

    def fetch_case(row: Row) -> list[str] | None:
        if not row.url:
            return None
        try:
            key = re.sub(r"\W+", "_", row.url)[-180:]
            page = read_url(row.url, outdir / "cache" / "cases" / f"{key}.html", refresh, timeout)
            row.parties, row.lawyers, row.check = parse_case(page)
            return None
        except Exception as exc:
            row.check = "case_error"
            return [row.court, row.hearing_date, row.url, type(exc).__name__, str(exc)]

    case_rows = [row for row in rows if row.url]
    if workers == 1 or len(case_rows) <= 1:
        case_errors = [fetch_case(row) for row in case_rows]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            case_errors = [future.result() for future in as_completed([pool.submit(fetch_case, row) for row in case_rows])]
    log.extend(error for error in case_errors if error)
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


def write_xlsx(path: Path, rows: list[list[str]], fns_rows: list[list[str]] | None = None) -> None:
    widths = [28, 12, 28, 13, 12, 24, 45, 24, 90, 90, 28, 55, 16]
    sheets = [("Report", rows)]
    if fns_rows is not None:
        sheets.append(("ФНС ЯНАО", fns_rows))

    def sheet_xml(sheet_rows: list[list[str]]) -> str:
        row_xmls = []
        for r, row in enumerate(sheet_rows, 1):
            cells = []
            for c, value in enumerate(row, 1):
                cells.append(f'<c r="{col_name(c)}{r}" s="{2 if r == 1 else 1}" t="inlineStr"><is><t>{escape(value or "")}</t></is></c>')
            row_xmls.append(f'<row r="{r}">{"".join(cells)}</row>')
        cols = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
        last = f"{col_name(len(HEADERS))}{max(len(sheet_rows), 1)}"
        return f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{cols}</cols><sheetData>{"".join(row_xmls)}</sheetData><autoFilter ref="A1:{last}"/></worksheet>'

    styles = '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyAlignment="1" applyFill="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        worksheet_overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + worksheet_overrides + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        sheet_defs = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + sheet_defs + "</sheets></workbook>")
        worksheet_rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + worksheet_rels + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", styles)
        for i, (_, sheet_rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(sheet_rows))


def write_html(path: Path, rows: list[list[str]]) -> None:
    body = []
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        body.append("<tr>" + "".join(f"<{tag}>{escape(value or '')}</{tag}>" for value in row) + "</tr>")
    path.write_text(
        '<!doctype html><meta charset="utf-8"><style>body{font-family:Arial,sans-serif;font-size:10px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;padding:4px;vertical-align:top}th{background:#eee}@page{size:A4 landscape;margin:8mm}</style><table>'
        + "".join(body)
        + "</table>",
        encoding="utf-8",
    )


def pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, rows: list[list[str]], html_path: Path | None = None) -> None:
    if html_path and shutil.which("libreoffice"):
        subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(path.parent), str(html_path)], check=True, timeout=180)
        converted = path.parent / f"{html_path.stem}.pdf"
        if converted.exists() and converted != path:
            converted.replace(path)
        if path.exists():
            return
    lines = [" | ".join(row[:8]) for row in rows[:200]]
    content = ["BT /F1 8 Tf 40 560 Td"]
    for line in lines:
        for part in textwrap.wrap(line, width=135)[:3]:
            content.append(f"({pdf_text(part)}) Tj 0 -10 Td")
        content.append("0 -4 Td")
    stream = ("\n".join(content) + "\nET").encode("cp1251", errors="replace")
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
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    data += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


def export_sud(
    date_from: str | date,
    date_to: str | date,
    outdir: str | Path,
    court: str | list[str] | None = None,
    refresh: bool = False,
    timeout: int = 30,
    workers: int = 6,
) -> dict[str, Path]:
    out = Path(outdir)
    rows, log = collect(date_from, date_to, out, court=court, refresh=refresh, timeout=timeout, workers=workers)
    table = [HEADERS] + sort_by_lawyer(rows)
    fns_table = [HEADERS] + sort_by_lawyer([row for row in rows if row_matches_fns_yanao(row)])
    paths = {
        "xlsx": out / "report.xlsx",
        "pdf": out / "report.pdf",
        "html": out / "report.html",
        "csv": out / "report.csv",
        "log": out / "run_log.csv",
    }
    write_xlsx(paths["xlsx"], table, fns_table)
    write_html(paths["html"], table)
    write_pdf(paths["pdf"], table, paths["html"])
    write_csv(paths["csv"], table)
    write_csv(paths["log"], [["Суд", "Дата", "URL", "Ошибка", "Детали"], *log])
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--court", action="append", help="court host or exact Russian court name; can be repeated")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--sort-by-lawyer", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    paths = export_sud(args.date_from, args.date_to, args.outdir, court=args.court, refresh=args.refresh, timeout=args.timeout, workers=args.workers)
    print(" ".join(f"{key}={path}" for key, path in paths.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
