from pathlib import Path
from urllib.parse import urlsplit

from docsetmcp.extractors.base import DashExtractor, extract_html_for_anchor


class FileSystemDirectoryExtractor(DashExtractor):
    @classmethod
    def is_format(cls, path: Path) -> bool:
        resources = path / "Contents" / "Resources"
        return (resources / "Documents").exists()

    def entry_as_markdown(self, name: str, doc_type: str, path: str) -> str | None:
        html_content = self._extract_by_path(path)

        if not html_content:
            return None

        if "#" in path:
            anchor = path.split("#", 1)[-1]
            html_content = extract_html_for_anchor(html_content, anchor)

        return self._format_html_as_markdown(html_content, name, doc_type, path)

    def _extract_by_path(self, html_path: str) -> str:
        """Extract HTML content from flat files."""
        url = urlsplit(html_path)
        assert url.netloc == ""
        full_path = self.documents_path / Path(url.path)
        if not full_path.resolve(strict=True).is_relative_to(self.documents_path):
            raise ValueError(
                f"Invalid path: {url.path!r} must be within docset Documents directory"
            )
        with full_path.open() as html_file:
            return html_file.read()
