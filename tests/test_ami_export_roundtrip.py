"""Regression tests: AMI must survive history reload and be visible in Excel."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from clustering_eval.application import ComparisonService, HistoryQueryService, RunRequest
from clustering_eval.results import HistoryStore

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _worksheet_cells(path: Path) -> dict[str, tuple[str, str]]:
    """Small OOXML check, with no dependency on Excel or its UI."""
    with ZipFile(path) as archive:
        shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        strings = [
            ''.join(t.text or '' for t in entry.iter(NS + 't'))
            for entry in shared.findall(NS + 'si')
        ]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        out = {}
        for cell in sheet.iter(NS + 'c'):
            value = cell.find(NS + 'v')
            if value is None:
                continue
            kind, raw = cell.get('t', 'n'), value.text or ''
            out[cell.attrib['r']] = (kind, strings[int(raw)] if kind == 's' else raw)
        return out


def test_ami_from_real_iris_survives_history_and_excel(tmp_path: Path) -> None:
    history_root = tmp_path / 'history'
    service = ComparisonService(history_store=HistoryStore(history_root))
    report = service.compare(RunRequest(
        mode='local', dataset_name='iris', algorithms=('kmeans', 'gmm'), seed=42,
    ))
    assert report.history_directory is not None
    history = HistoryQueryService(history_root).get_experiment(report.history_directory.name)
    assert len(report.results) == len(history.results) == 2
    for original, loaded in zip(report.results, history.results):
        assert original.ami is not None
        assert loaded.ami == pytest.approx(original.ami)
        assert loaded.nmi == pytest.approx(original.nmi)

    path = tmp_path / 'with_ami.xlsx'
    service.export_excel(report, str(path))
    cells = _worksheet_cells(path)
    # ARI/AMI/NMI must appear together, not with AMI in a far-right column.
    for ref, name in [('F16', 'ARI'), ('G16', 'AMI'), ('H16', 'NMI')]:
        assert cells[ref] == ('s', name)
    for row, result in enumerate(report.results, start=17):
        kind, raw = cells[f'G{row}']
        assert kind == 'n', 'AMI must be an Excel number, not a text string'
        assert float(raw) == pytest.approx(result.ami)


def test_legacy_history_without_ami_can_still_load() -> None:
    result = HistoryQueryService._to_algorithm_result({
        'algorithm': 'legacy', 'backend': 'local', 'ari': 0.5, 'nmi': 0.4,
    })
    assert result.ami is None
