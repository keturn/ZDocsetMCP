import pytest

from docsetmcp.extractors.base import extract_html_for_anchor


def test_extract_html_dash_anchor(pytestconfig):
    html_path = pytestconfig.rootpath / "tests" / "data" / "b" / "anchors.html"
    html_src = html_path.read_text()
    region = extract_html_for_anchor(html_src, "//apple_ref/Function/itertools.chain")
    assert "itertools.chain" in region
    assert "itertools.islice" not in region
    assert "helpful descriptive text" in region
    assert "should not be included" not in region


def test_extract_html_texinfo_dl(pytestconfig):
    html_path = pytestconfig.rootpath / "tests" / "data" / "b" / "texinfo-anchors.html"
    html_src = html_path.read_text()
    region = extract_html_for_anchor(html_src, "//apple_ref/Builtin/true")
    assert "true" in region
    assert "test" not in region
    assert "returns a 0 status" in region
    assert "end of the document" not in region


def test_extract_html_multiple_dt(pytestconfig):
    html_path = pytestconfig.rootpath / "tests" / "data" / "b" / "texinfo-anchors.html"
    html_src = html_path.read_text()
    # `test` is a tricky case because there are multiple <dt> elements (including its alias `[`)
    region = extract_html_for_anchor(html_src, "//apple_ref/Builtin/test")
    assert "test" in region
    assert "[" in region
    assert "0 status" not in region
    assert "conditional expression" in region
    assert "end of the document" not in region


def test_extract_mdn_dl(pytestconfig):
    html_path = pytestconfig.rootpath / "tests" / "data" / "b" / "mdn-anchors.html"
    html_src = html_path.read_text()
    region = extract_html_for_anchor(html_src, "//apple_ref/Attribute/name")
    assert "name of the form" in region
    assert "autocomplete" not in region
    assert "links" not in region
    assert "end of the document" not in region


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
