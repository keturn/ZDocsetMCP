import io
import mmap
import tarfile
from compression import zlib
from dataclasses import dataclass
from pathlib import Path

from docsetmcp.db_util import connect_readonly
from docsetmcp.extractors.base import DashExtractor, extract_html_for_anchor


class TarixExtractor(DashExtractor):
    @classmethod
    def is_format(cls, path: Path) -> bool:
        resources = path / "Contents" / "Resources"
        return (resources / "tarix.tgz").exists()

    def __init__(self, path: Path):
        super().__init__(path)
        resources = path / "Contents" / "Resources"
        self.tarix_archive = resources / "tarix.tgz"
        self.tarix_index = resources / "tarixIndex.db"
        # Cache for extracted HTML content
        self.html_cache: dict[str, str] = {}

    def entry_as_markdown(self, name: str, doc_type: str, path: str) -> str | None:
        html_content = self._extract_from_tarix(path)

        if not html_content:
            return None

        if "#" in path:
            anchor = path.split("#", 1)[-1]
            html_content = extract_html_for_anchor(html_content, anchor)

        return self._format_html_as_markdown(html_content, name, doc_type, path)

    def _extract_from_tarix(self, search_path: str) -> str | None:
        """Extract HTML content from tarix archive"""
        # Remove anchor from path
        clean_path = search_path.split("#")[0]

        # Handle special Dash metadata paths (like in C docset)
        if clean_path.startswith("<dash_entry_"):
            # Extract the actual file path from the end of the path
            # Format: <dash_entry_...>actual/file/path.html
            parts = clean_path.split(">")
            if len(parts) > 1:
                clean_path = parts[-1]  # Get the actual file path after the last >

        # Check cache first
        if clean_path in self.html_cache:
            return self.html_cache[clean_path]

        try:
            raw_file = self._extract_raw_from_tarix(search_path)[0]
            if raw_file is not None:
                content = raw_file.decode("utf-8", errors="ignore")
                self.html_cache[clean_path] = content
                return content

        except FileNotFoundError:
            pass

        return None

    def _extract_raw_from_tarix(self, search_path: str) -> tuple[bytes, int] | None:
        # Remove anchor from path
        clean_path = search_path.split("#")[0]

        # Handle special Dash metadata paths (like in C docset)
        if clean_path.startswith("<dash_entry_"):
            # Extract the actual file path from the end of the path
            # Format: <dash_entry_...>actual/file/path.html
            parts = clean_path.split(">")
            if len(parts) > 1:
                clean_path = parts[-1]  # Get the actual file path after the last >

        # Build full docset path
        # Extract docset folder name from docset_path (e.g., "NodeJS/NodeJS.docset" -> "NodeJS.docset")
        docset_folder = self._config["docset_path"].split("/")[-1]
        full_path = f"{docset_folder}/Contents/Resources/Documents/{clean_path}"

        if self.tarix_index.exists():
            record = self._get_tarix_index(full_path)
            if record:
                return self._tarix_extract_by_index(record.offset, record.size)

        return self._tarix_extract_as_tar(full_path, clean_path)

    def _tarix_extract_by_index(self, offset: int, size: int) -> tuple[bytes, int]:
        TAR_BLOCK_SIZE = 512
        with open(self.tarix_archive, "rb") as compressed_file:
            mm = mmap.mmap(
                compressed_file.fileno(),
                0,
                access=mmap.ACCESS_READ,
            )[offset : offset + size * TAR_BLOCK_SIZE]
            decompressor = zlib.decompressobj(wbits=-zlib.MAX_WBITS)  # cspell:ignore wbits
            decompressed_blocks = decompressor.decompress(mm)
            with tarfile.open(mode="r:", fileobj=io.BytesIO(decompressed_blocks)) as tar:
                member = tar.next()
                return tar.extractfile(member).read(), member.mtime

    def _tarix_extract_as_tar(self, full_path: str, clean_path: str) -> tuple[bytes, int] | None:
        with tarfile.open(self.tarix_archive, "r:gz") as tar:
            try:
                target_member = tar.getmember(full_path)
                if (reader := tar.extractfile(target_member)) is not None:
                    return reader.read(), target_member.mtime
            except KeyError:
                # If exact path fails, try to find by name
                target_file = full_path.split("/")[-1]  # Get just the filename
                for member in tar.getmembers():
                    if (
                        member.name.endswith(target_file)
                        and clean_path in member.name
                        and (reader := tar.extractfile(member)) is not None
                    ):
                        return reader.read(), member.mtime

    def _get_tarix_index(self, search_path: str) -> TarixRecord:
        conn = connect_readonly(self.tarix_index)
        cursor = conn.cursor()

        cursor.execute("SELECT hash FROM tarindex WHERE path = ?", (search_path,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            return None
        return TarixRecord.from_string(result[0])


@dataclass
class TarixRecord:
    entry_number: int
    offset: int
    size: int

    @classmethod
    def from_string(cls, s: str) -> TarixRecord:
        parts = s.split()
        if len(parts) != 3:
            raise ValueError(f"Expected three parts in {parts:r}")
        return cls(*[int(x) for x in parts])
