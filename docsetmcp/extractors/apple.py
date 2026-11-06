import base64
import hashlib
from pathlib import Path

import brotli

from docsetmcp.common import AppleDocumentation, ContentItem
from docsetmcp.db_util import connect_readonly
from docsetmcp.extractors.base import DashExtractor


class AppleExtractor(DashExtractor):
    @classmethod
    def is_format(cls, path: Path) -> bool:
        resources = path / "Contents" / "Resources"
        return (resources / "cache.db").exists()

    def __init__(self, path: Path):
        super().__init__(path)
        resources = path / "Contents" / "Resources"
        self.fs_dir = resources / "Documents" / "fs"
        self.cache_db = resources / "cache.db"
        # Cache for decompressed fs files
        self.fs_cache: dict[int, bytes] = {}

    def entry_as_markdown(self, name: str, doc_type: str, path: str):
        if "request_key=" in path:
            request_key: str = path.split("request_key=")[1].split("#")[0]
            # Remove any language parameter from request_key
            if "&" in request_key:
                request_key = request_key.split("&")[0]

            path_language = path.split("&language=")[1].split("&")[0].split("#")[0]

            doc = self._extract_by_request_key(request_key, path_language)

            if doc:
                markdown = self._format_as_markdown(doc, name, doc_type)
                return markdown

    def _extract_by_request_key(
        self, request_key: str, language: str = "swift"
    ) -> AppleDocumentation | None:
        """Extract documentation using request key and SHA-1 encoding"""
        # Convert request_key to canonical path
        if request_key.startswith("ls/"):
            canonical_path = "/" + request_key[3:]
        else:
            canonical_path = "/" + request_key

        # Calculate UUID using SHA-1
        sha1_hash = hashlib.sha1(canonical_path.encode("utf-8")).digest()
        truncated = sha1_hash[:6]
        suffix = base64.urlsafe_b64encode(truncated).decode().rstrip("=")

        # Language prefix from config
        lang_config = self._config["languages"][language]
        prefix = lang_config["prefix"]
        uuid = prefix + suffix

        conn = connect_readonly(self.cache_db)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT data_id, offset, length
            FROM refs
            WHERE uuid = ?
            """,
            (uuid,),
        )

        result = cursor.fetchone()
        conn.close()

        if result:
            data_id, offset, length = result
            return self._extract_from_fs(data_id, offset, length)

        return None

    def _extract_from_fs(self, data_id: int, offset: int, length: int) -> AppleDocumentation | None:
        """Extract JSON from fs file at specific offset"""
        fs_file = self.fs_dir / str(data_id)

        if not fs_file.exists():
            return None

        try:
            # Load and cache decompressed data
            if data_id not in self.fs_cache:
                with open(fs_file, "rb") as f:
                    compressed = f.read()
                self.fs_cache[data_id] = brotli.decompress(compressed)

            decompressed = self.fs_cache[data_id]

            # Extract JSON at offset
            json_data = decompressed[offset : offset + length]
            import json

            doc = json.loads(json_data)

            if "metadata" in doc:
                return doc

        except FileNotFoundError:
            pass

        return None

    # noinspection PyTypedDict
    def _format_as_markdown(self, doc: AppleDocumentation, name: str, doc_type: str) -> str:
        """Format documentation as Markdown"""
        lines: list[str] = []
        metadata = doc.get("metadata", {})

        # Title
        title = metadata.get("title", name)
        lines.append(f"# {title}")

        # Type
        lines.append(f"\n**Type:** {doc_type}")

        # Framework
        modules = metadata.get("modules", [])  # type: ignore
        if modules:
            names = [m.get("name", "") for m in modules]  # type: ignore
            lines.append(f"**Framework:** {', '.join(names)}")

        # Availability
        platforms = metadata.get("platforms", [])  # type: ignore
        if platforms:
            avail: list[str] = []
            for p in platforms:
                platform_name = p.get("name", "")
                ver = p.get("introducedAt", "")
                if ver:
                    avail.append(f"{platform_name} {ver}+")
                else:
                    avail.append(platform_name)
            if avail:
                lines.append(f"**Available on:** {', '.join(avail)}")

        # Abstract/Summary
        abstract = doc.get("abstract", [])  # type: ignore
        if abstract:
            text = self._extract_text(abstract)  # type: ignore
            if text:
                lines.append(f"\n## Summary\n\n{text}")

        # Primary Content Sections
        sections = doc.get("primaryContentSections", [])
        for section in sections:  # type: ignore
            kind = section.get("kind", "")

            if kind == "declarations":
                decls = section.get("declarations", [])
                if decls and decls[0].get("tokens"):
                    lines.append("\n## Declaration\n")
                    tokens = decls[0].get("tokens", [])
                    code = "".join(t.get("text", "") for t in tokens)
                    lang = decls[0].get("languages", ["swift"])[0]
                    lines.append(f"```{lang}\n{code}\n```")

            elif kind == "parameters":
                params = section.get("parameters", [])
                if params:
                    lines.append("\n## Parameters\n")
                    for param in params:
                        param_name = param.get("name", "")
                        param_content = param.get("content", [])
                        param_text = self._extract_text(param_content)
                        if param_name and param_text:
                            lines.append(f"- **{param_name}**: {param_text}")

            elif kind == "content":
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    lines.append(f"\n{text}")

            # Handle other section types as generic content
            elif "content" in section:
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    section_title = kind.replace("_", " ").title()
                    lines.append(f"\n## {section_title}\n\n{text}")

        # Discussion
        discussion = doc.get("discussionSections", [])
        if discussion:
            lines.append("\n## Discussion")
            for section in discussion:  # Get all discussion sections
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    lines.append(f"\n{text}")

        return "\n".join(lines)

    def _extract_text(self, content: list[ContentItem]) -> str:
        """Extract plain text from content"""
        parts: list[str] = []
        for item in content:
            t = item.get("type", "")
            if t == "text":
                parts.append(item.get("text", ""))
            elif t == "codeVoice":
                parts.append(f"`{item.get('code', '')}`")
            elif t == "paragraph":
                inline = item.get("inlineContent", [])
                parts.append(self._extract_text(inline))
            elif t == "reference":
                title = item.get("title", item.get("identifier", ""))
                parts.append(f"`{title}`")
        return " ".join(parts)
