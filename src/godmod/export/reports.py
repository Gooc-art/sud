from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from ..models import ReportBundle
from ..report_rows import build_report_rows
from .excel import SheetSpec, write_workbook
from .pdf import write_pdf_report


ALL_ACCOUNTS_COLUMN_WIDTHS = {
    "id": 14.0,
    "Название": 24.0,
    "Тип": 18.0,
    "Ссылка": 28.0,
    "Город / локация": 18.0,
    "Адрес (если есть)": 24.0,
    "Описание деятельности": 34.0,
    "Ключевые слова услуг": 22.0,
    "Подписчики": 12.0,
    "Активность (постинг)": 18.0,
    "Постов за 30 дней": 14.0,
    "Средние лайки": 14.0,
    "Средние комментарии": 18.0,
    "Средние репосты": 16.0,
    "ER, %": 10.0,
    "Коммерческие маркеры": 24.0,
    "Сотрудники": 18.0,
    "Контакты администратора": 26.0,
    "Ссылка для записи": 28.0,
    "Дата сбора": 18.0,
    "Примечание": 34.0,
}


@dataclass(slots=True)
class ReportArtifacts:
    workbook: Path
    pdf: Path | None
    manifest: Path | None = None
    manifest_payload: dict[str, object] | None = None
    history: Path | None = None
    pdf_error: str | None = None


def write_report_artifacts(bundle: ReportBundle, workbook_path: str | Path) -> ReportArtifacts:
    return write_report_artifacts_with_timing(bundle, workbook_path)


def write_report_artifacts_with_timing(
    bundle: ReportBundle,
    workbook_path: str | Path,
    *,
    started_at: datetime | None = None,
    collected_at: datetime | None = None,
    report_origin: str | None = None,
) -> ReportArtifacts:
    target = Path(workbook_path)
    export_started_at = datetime.now(UTC)
    rows = build_report_rows(bundle)
    workbook = write_workbook(
        target,
        [_sheet_spec(name, sheet_rows) for name, sheet_rows in rows.items()],
    )
    pdf_path = workbook.with_suffix(".pdf")
    manifest_path = workbook.with_suffix(".json")
    history_path = workbook.parent / "run_history.jsonl"

    pdf: Path | None = None
    pdf_error: str | None = None
    try:
        pdf = write_pdf_report(pdf_path, bundle, rows)
    except Exception as exc:  # noqa: BLE001
        pdf_error = str(exc)

    manifest_payload = _build_manifest_payload(
        bundle=bundle,
        workbook=workbook,
        pdf=pdf,
        pdf_error=pdf_error,
        rows=rows,
        started_at=started_at,
        collected_at=collected_at,
        export_started_at=export_started_at,
        report_origin=report_origin,
    )
    _write_manifest(manifest_path, manifest_payload)
    _append_run_history(history_path, manifest_payload)
    return ReportArtifacts(
        workbook=workbook,
        pdf=pdf,
        manifest=manifest_path,
        manifest_payload=manifest_payload,
        history=history_path,
        pdf_error=pdf_error,
    )


def _sheet_spec(name: str, rows: list[dict[str, object]]) -> SheetSpec:
    if name == "all_accounts":
        return SheetSpec(
            name=name,
            rows=rows,
            freeze_header=True,
            auto_filter=True,
            column_widths=ALL_ACCOUNTS_COLUMN_WIDTHS,
        )
    return SheetSpec(name=name, rows=rows)


def _build_manifest_payload(
    *,
    bundle: ReportBundle,
    workbook: Path,
    pdf: Path | None,
    pdf_error: str | None,
    rows: dict[str, list[dict[str, object]]],
    started_at: datetime | None,
    collected_at: datetime | None,
    export_started_at: datetime,
    report_origin: str | None,
) -> dict[str, object]:
    finished_at = datetime.now(UTC)
    meta = dict(bundle.report_meta)
    if report_origin and not str(meta.get("report_origin", "")).strip():
        meta["report_origin"] = report_origin
    if started_at is not None:
        meta["started_at"] = started_at.isoformat()
    if collected_at is not None:
        meta["collected_at"] = collected_at.isoformat()
        if started_at is not None:
            meta["collection_duration_seconds"] = round((collected_at - started_at).total_seconds(), 3)
    meta["export_started_at"] = export_started_at.isoformat()
    meta["finished_at"] = finished_at.isoformat()
    meta["export_duration_seconds"] = round((finished_at - export_started_at).total_seconds(), 3)
    if started_at is not None:
        meta["duration_seconds"] = round((finished_at - started_at).total_seconds(), 3)
    return {
        "generated_at": finished_at.isoformat(),
        "workbook": str(workbook),
        "pdf": {
            "path": str(pdf) if pdf is not None else "",
            "status": "created" if pdf is not None else "failed",
            "error": pdf_error or "",
        },
        "request": {
            "cities": list(bundle.request.cities),
            "services": [service.name for service in bundle.request.services],
            "period_days": bundle.request.period_days,
            "platforms": list(bundle.request.platforms),
            "top_n": bundle.request.top_n,
            "report_mode": bundle.request.report_mode,
        },
        "counts": {
            "ranked_accounts": len(bundle.ranked_accounts),
            "raw_candidates": len(bundle.raw_candidates),
            "duplicates_review": len(bundle.duplicates_review),
            "filter_debug": len(bundle.filter_debug),
            "search_log": len(bundle.search_log),
        },
        "sheets": {name: len(sheet_rows) for name, sheet_rows in rows.items()},
        "meta": meta,
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_run_history(path: Path, payload: dict[str, object]) -> None:
    history_entry = {
        "generated_at": payload.get("generated_at", ""),
        "workbook": payload.get("workbook", ""),
        "pdf": payload.get("pdf", {}),
        "request": payload.get("request", {}),
        "counts": payload.get("counts", {}),
        "meta": payload.get("meta", {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(history_entry, ensure_ascii=False))
        handle.write("\n")
