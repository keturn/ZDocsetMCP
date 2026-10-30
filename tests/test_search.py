from collections import defaultdict
from pathlib import Path
from textwrap import dedent

import pytest

from docsetmcp.common import ProcessedLanguageConfig
from docsetmcp.dash_extractor import DashExtractor, _format_search_results


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


def test_format_single_result():
    expected = "Entry Text"
    formatted = _format_search_results("Something", [expected])
    assert formatted == expected


def test_format_several_results():
    title1 = "First Thing"
    title2 = "Second Thing"
    detail1 = "Blah blah more text."
    detail2 = "Something something."
    results: list[str] = [
        dedent(f"""\
            ---
            Title: {title1}
            Type: Function
            Document-Source: things.html#first
            ---

            The first of things.

            {detail1}
            """),
        dedent(f"""\
            ---
            Title: {title2}
            Type: Function
            Document-Source: things.html#second
            ---

            A different thing.

            {detail2}.
            """),
    ]

    formatted = _format_search_results("Thing", results)
    assert title1 in formatted
    assert title2 in formatted
    assert detail1 not in formatted
    assert detail2 not in formatted
