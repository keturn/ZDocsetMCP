import pytest

from docsetmcp.dash_extractor import extract_html_for_anchor


def test_extract_html_dash_anchor(pytestconfig):
    html_path = pytestconfig.rootpath / "tests" / "data" / "b" / "anchors.html"
    html_src = html_path.read_text()
    region = extract_html_for_anchor(html_src, "//apple_ref/Function/itertools.chain")
    assert "itertools.chain" in region
    assert "itertools.islice" not in region
    assert "helpful descriptive text" in region
    assert "should not be included" not in region


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
