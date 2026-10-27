from collections import defaultdict
from pathlib import Path

import pytest

from docsetmcp.common import ProcessedLanguageConfig
from docsetmcp.dash_extractor import DashExtractor


class IndexOnlyExtractor(DashExtractor):
    def __init__(self, path: Path):
        super().__init__(path)
        # FIXME: come back to this language determination and filtering
        self.languages = defaultdict(lambda: ProcessedLanguageConfig(filter="", prefix=""))

    @classmethod
    def is_format(cls, path: Path) -> bool:
        return (path / "Contents" / "Resources" / "docSet.dsidx").exists()

    def entry_as_markdown(self, name: str, doc_type: str, path: str, language) -> str | None:
        raise NotImplementedError("IndexOnlyExtractor does not provide full text.")


def test_zero_results(pytestconfig):
    extractor = IndexOnlyExtractor(
        pytestconfig.rootpath / "tests" / "data" / "c" / "FragmentExample.docset"
    )
    additional, records, _e1, _e2, found_exact = extractor._search_records(
        "xyzzlbax4",  # cspell: disable-line
        "python",
        10,
    )
    assert additional == 0
    assert len(records) == 0
    assert not found_exact


@pytest.mark.parametrize(
    "docset,query,expected",
    [
        (
            "FragmentExample.docset",
            "itertools.cycle",
            "doc/library/itertools.html#//apple_ref/Function/itertools.cycle",
        ),
        (
            "UnifiedExample.docset",
            "umask",
            "bash/Bourne-Shell-Builtins.html#//apple_ref/Builtin/umask",
        ),
    ],
)
def test_single_result_has_fragment(pytestconfig, docset, query, expected):
    extractor = IndexOnlyExtractor(pytestconfig.rootpath / "tests" / "data" / "c" / docset)
    additional, records, exact_name, _e2, found_exact = extractor._search_records(
        query, "python", 10
    )
    assert additional == 0
    assert found_exact
    assert exact_name == query
    assert len(records) == 1
    record = records[0]
    assert record[0] == query
    assert record[2] == expected
