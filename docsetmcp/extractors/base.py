import json
import logging
import plistlib
import re
import sqlite3
from abc import ABCMeta, abstractmethod
from pathlib import Path
from plistlib import InvalidFileException

import bs4
import html_to_markdown
import yaml

from docsetmcp.common import ProcessedDocsetConfig
from docsetmcp.config_loader import ConfigLoader
from docsetmcp.db_util import connect_readonly, escape_like_pattern, has_column, make_unique

logger = logging.getLogger(__name__)


class DashExtractor(metaclass=ABCMeta):
    _config: ProcessedDocsetConfig
    path: Path
    identifiers: list[str]
    titles: list[str]
    description: str | None = None
    primary_language: str

    @classmethod
    @abstractmethod
    def is_format(cls, path: Path) -> bool:
        raise NotImplementedError()

    def __init__(self, path: Path):
        self.path: Path = path

        if not self.path.exists():
            raise FileNotFoundError(f"Docset path not found: {self.path}")

        resources = self.path / "Contents" / "Resources"
        self.documents_path = resources / "Documents"
        self.starting_document = "index.html"

        loader = ConfigLoader()

        self.identifiers = []
        self.titles = []

        self._load_plist()
        self._load_zeal_metadata()

        try:
            self._config = loader.load_config(path.name.replace(".docset", ""))
            self.titles.append(self._config["name"])
            self.description = self._config.get("description")
        except FileNotFoundError:
            if auto_config := loader._generate_config_from_docset(path):  # type: ignore
                self._config = auto_config
            else:
                raise RuntimeError(f"Failed to load or auto-generate config for docset at {path}")

        make_unique(self.identifiers)
        make_unique(self.titles)

        if not self.identifiers:
            self.identifiers.append(path.stem)
        if not self.titles:
            self.titles.append(self.identifiers[0])

        self.languages = self._config.get("languages", {})
        self.primary_language = infer_primary_language(self._config)

        # Set up paths based on docset format
        if (resources / "optimizedIndex.dsidx").exists():
            self.search_index_db = resources / "optimizedIndex.dsidx"
        else:
            self.search_index_db = resources / "docSet.dsidx"

    @property
    def id(self) -> str:
        return self.identifiers[0]

    @property
    def title(self) -> str:
        return self.titles[0]

    @property
    def language_names(self) -> list[str]:
        return list(self.languages.keys())

    def _load_plist(self):
        plist_path = self.path / "Contents" / "Info.plist"

        try:
            with plist_path.open("rb") as f:
                plist_data = plistlib.load(f)
        except FileNotFoundError:
            logger.warning("Info.plist not found in %s. This is unusual.", plist_path.parent)
            return
        except InvalidFileException:
            logger.warning("Invalid plist file at %s", plist_path)
            return

        if bundle_id := plist_data.get("CFBundleIdentifier"):
            self.identifiers.append(bundle_id)

        if bundle_name := plist_data.get("CFBundleName"):
            self.titles.append(bundle_name)

        if index_file := plist_data.get("dashIndexFilePath"):
            self.starting_document = index_file

    def _load_zeal_metadata(self):
        try:
            with (self.path / "meta.json").open() as f:
                metadata = json.load(f)
        except FileNotFoundError:
            if re.search("zeal", str(self.path), re.IGNORECASE):
                logger.debug("Zeal meta.json not found in %s.", self.path.name)
            else:
                pass  # Not expected to be present on non-Zeal systems.
            return

        if name := metadata.get("name"):
            self.identifiers.append(name)
        if title := metadata.get("title"):
            self.titles.append(title)

    def _search_index(self) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
        """A read-only connection to the search index database."""
        conn = connect_readonly(self.search_index_db)
        cursor = conn.cursor()
        return conn, cursor

    def _normalize_query(self, query: str) -> list[str]:
        """Normalize query for better matching"""
        # Remove extra spaces and convert to consistent format
        normalized = " ".join(query.split())
        # Also create a no-space version for cases like "App Intent" -> "AppIntent"
        no_spaces = normalized.replace(" ", "")
        # Return unique variations
        variations = [query]
        if normalized != query:
            variations.append(normalized)
        if no_spaces != query and no_spaces != normalized:
            variations.append(no_spaces)
        return variations

    def search(self, query: str, max_results: int = 3) -> str:
        """Search for a specific documentation entry"""

        additional_members, db_results, exact_match_name, exact_match_type, found_exact_match = (
            self._search_records(query, max_results)
        )

        if not db_results:
            return f"No matches found for '{query}' in {self.title} documentation"

        # Extract documentation for each result
        results: list[str] = []
        for row in db_results[:max_results]:
            name, doc_type, path, *_ = row
            if (markdown := self.entry_as_markdown(name, doc_type, path)) is not None:
                # Add member note if this is the exact match and has members
                if (
                    found_exact_match
                    and name == exact_match_name
                    and doc_type == exact_match_type
                    and additional_members > 0
                ):
                    type_note = f"\n\n**Note:** The {exact_match_name} {doc_type.lower()} contains {additional_members} additional members not shown. Use `search_docs('{exact_match_name}', max_results=50)` to see all {exact_match_name} members."
                    markdown += type_note
                results.append(markdown)

        # Handle different result counts appropriately
        if results:
            return _format_search_results(query, results)

        # Found entries but couldn't extract
        entries_info: list[str] = []
        for name, doc_type, *_ in db_results[:10]:  # Show up to 10 entries found
            entries_info.append(f"- {name} ({doc_type})")

        return f"""Found entries for '{query}' but couldn't extract documentation. The content may not be in the offline cache.

Found but couldn't extract:
{chr(10).join(entries_info)}

Try opening Dash and ensuring the '{self._config["name"]}' docset is fully downloaded."""

    def _search_index_cte(self, cursor: sqlite3.Cursor):
        """Provide a consistent view of the path field as combined path#fragment."""
        if has_column(cursor, "searchIndex", "fragment"):
            return 'SELECT name, type, concat(searchIndex.path, "#", searchIndex.fragment) as path from searchIndex'
        else:
            return "SELECT name, type, path from searchIndex"

    def _search_records(
        self, query: str, max_results: int
    ) -> tuple[int, list[tuple[str, str, str]], str | None, str | None, bool]:
        conn, cursor = self._search_index()

        query_variations = self._normalize_query(query)

        # Get top-level types from configuration
        if self._config.get("types"):
            # Sort types by their priority value and take the first few
            sorted_types = sorted(self._config["types"].items(), key=lambda x: x[1])
            top_types = [type_name for type_name, _ in sorted_types[:5]]
        else:
            # If no types configured, we can't filter by type
            top_types = []

        type_list = ", ".join(f"'{t}'" for t in top_types) if top_types else "''"

        # Collect all results, not just from first successful query
        all_results: list[tuple[str, str, str]] = []
        seen_entries: set[tuple[str, str]] = set()  # Track (name, type) to avoid duplicates

        # Normalize path and fragment fields
        search_index_3 = self._search_index_cte(cursor)

        # Try exact match with all query variations (case-insensitive)
        cursor.execute(
            f"""
            WITH searchIndex3 AS ({search_index_3})
            SELECT DISTINCT name, type, path
            FROM searchIndex3
            WHERE name COLLATE NOCASE IN (SELECT value FROM json_each(:query))
            ORDER BY :type_order ->> type OR 999
            LIMIT :max
        """,
            {
                "query": json.dumps(query_variations),
                "type_order": json.dumps(self._config["types"]) or {},
                "max": max_results,
            },
        )
        for row in cursor.fetchall():
            key = (row[0], row[1])
            if key not in seen_entries:
                all_results.append(row)
                seen_entries.add(key)

        # Check if we found an exact match in the results
        found_exact_match: bool = False
        exact_match_name: str | None = None
        exact_match_path: str | None = None
        exact_match_type: str | None = None

        for row in all_results:
            if len(row) >= 3 and row[0].lower() == query.lower():
                found_exact_match = True
                exact_match_name = row[0]
                exact_match_type = row[1]
                exact_match_path = row[2]
                break

        # Track additional members count
        additional_members = 0

        # Count total members for exact matches to show in the note
        if found_exact_match and exact_match_name and exact_match_path:
            # Extract the documentation path pattern
            doc_path_pattern = ""
            if "/documentation/" in exact_match_path:
                doc_path = exact_match_path.split("/documentation/")[1].split("?")[0].split("#")[0]
                doc_path_pattern = f"%/documentation/{doc_path}/%"

            if doc_path_pattern:
                # Count total members for the note (but don't include them in results)
                cursor.execute(
                    f"""
                    WITH searchIndex3 AS ({search_index_3})
                    SELECT COUNT(*)
                    FROM searchIndex3
                    WHERE path LIKE ?
                      AND name != ?
                    """,
                    (doc_path_pattern, exact_match_name),
                )
                total_count = cursor.fetchone()
                if total_count:
                    additional_members = total_count[0]

        # If we still need more results, try broader search
        if not found_exact_match and len(all_results) < max_results:
            cursor.execute(
                f"""
                WITH searchIndex3 AS ({search_index_3})
                SELECT name, type, path FROM searchIndex3
                WHERE name LIKE :prefix ESCAPE char(0x1B)
                ORDER BY :type_order ->> type OR 999, LENGTH(name), name COLLATE NOCASE
                LIMIT :max
            """,
                {
                    "prefix": f"{escape_like_pattern(query)}%",
                    "type_order": json.dumps(self._config["types"]) or {},
                    "max": max_results - len(all_results),
                },
            )
            for row in cursor.fetchall():
                if len(all_results) >= max_results:
                    break
                key = (row[0], row[1])
                if key not in seen_entries:
                    all_results.append(row)
                    seen_entries.add(key)

        conn.close()

        # Use all_results instead of db_results
        db_results: list[tuple[str, str, str]] = all_results[:max_results]
        return additional_members, db_results, exact_match_name, exact_match_type, found_exact_match

    @abstractmethod
    def entry_as_markdown(self, name: str, doc_type: str, path: str) -> str | None: ...

    def list_frameworks(self, filter_text: str | None = None) -> str:
        """List available frameworks/modules"""
        conn, cursor = self._search_index()

        if self._config["format"] == "apple" and self._config.get("framework_pattern"):
            framework_pattern = self._config["framework_pattern"]

            if "documentation/" in framework_pattern:
                query = """
                    SELECT DISTINCT
                        SUBSTR(path,
                            INSTR(path, 'documentation/') + 14,
                            INSTR(SUBSTR(path, INSTR(path, 'documentation/') + 14), '/') - 1
                        ) as framework
                    FROM searchIndex
                    WHERE path LIKE '%documentation/%'
                """
            else:
                # Fallback to generic pattern matching
                query = f"""
                    SELECT DISTINCT path
                    FROM searchIndex
                    WHERE path LIKE '%{framework_pattern}%'
                    LIMIT 100
                """

            if filter_text:
                query = query.replace("WHERE", f"WHERE framework LIKE '%{filter_text}%' AND")

            cursor.execute(query)

            if "documentation/" in framework_pattern:
                frameworks = [row[0] for row in cursor.fetchall() if row[0]]
            else:
                # Extract framework names from paths manually
                paths = [row[0] for row in cursor.fetchall()]
                frameworks: list[str] = []
                import re

                pattern_regex = framework_pattern.replace("([^/]+)", "([^/]+)")
                for path in paths:
                    match = re.search(pattern_regex, path)
                    if match and match.group(1):
                        frameworks.append(match.group(1))

            # Remove duplicates and empty strings
            frameworks = sorted(set(f for f in frameworks if f))

            label = "frameworks"
        else:
            # For other docsets, just list available types
            query = "SELECT DISTINCT type FROM searchIndex ORDER BY type"
            cursor.execute(query)
            frameworks = [row[0] for row in cursor.fetchall() if row[0]]
            label = "types"

        conn.close()

        if filter_text:
            return f"{label.title()} matching '{filter_text}':\n" + "\n".join(
                f"- {f}" for f in frameworks if filter_text.lower() in f.lower()
            )
        else:
            return f"Available {label} ({len(frameworks)} total):\n" + "\n".join(
                f"- {f}" for f in frameworks
            )

    def _format_html_as_markdown(
        self, html_content: str, name: str, doc_type: str, path: str
    ) -> str:
        """Convert HTML documentation to Markdown"""
        lines: list[str] = [
            yaml.dump(
                {"Title": name, "Type": doc_type, "Document-Source": path},
                explicit_start=True,
                sort_keys=False,
            )
            + "---\n",
        ]

        lang = next(iter(self._config["languages"].keys()), "")
        text_content = html_to_markdown.convert(
            html_content,
            html_to_markdown.ConversionOptions(
                heading_style="atx", extract_metadata=False, code_language=lang
            ),
        ).content

        # Limit content length
        if len(text_content) > 2000:
            text_content = text_content[:2000] + "..."

        if text_content:
            lines.append(text_content)

        return "\n".join(lines)


def _format_search_results(query: str, results: list[str]) -> str:
    if len(results) == 1:
        # Single result: return full content
        return results[0]
    elif 2 <= len(results) <= 5:
        # 2-5 results: return summaries with option to search individually
        summaries: list[str] = []
        for i, full_content in enumerate(results, 1):
            lines = full_content.split("\n")
            title = f"Result {i}"
            # Get title and key info
            if lines[0] == "---":
                front_matter = next(yaml.safe_load_all(full_content))
                if "Title" in front_matter:
                    title = front_matter["Title"]
            else:
                title = lines[0]
            summary_lines = [f"{i}. {title}"]

            # Add type and framework info
            for line in lines[1:10]:
                if line.startswith(("**Type:**", "**Framework:**")):
                    summary_lines.append(f"   {line}")

            # Add first line of summary if available
            for j, line in enumerate(lines):
                if line == "## Summary" and j + 2 < len(lines):
                    summary_text = lines[j + 2]
                    if len(summary_text) > 100:
                        summary_text = summary_text[:100] + "..."
                    summary_lines.append(f"   {summary_text}")
                    break

            summaries.append("\n".join(summary_lines))

        header = f"Found {len(results)} results for '{query}':\n\n"
        footer = "\n\nSearch for each item individually to see full documentation."
        return header + "\n\n".join(summaries) + footer
    elif len(results) <= 100:
        # 6-100 results: return full content with separators
        return "\n\n---\n\n".join(results)
    else:
        # More than 100: show count and suggest refinement
        # In future, could implement pagination here
        entry_list: list[str] = []
        for full_content in results[:100]:
            lines = full_content.split("\n")
            title = lines[0].replace("# ", "") if lines else "Unknown"
            doc_type = "Unknown"
            framework = ""
            for line in lines[1:5]:
                if line.startswith("**Type:**"):
                    doc_type = line.replace("**Type:** ", "")
                elif line.startswith("**Framework:**"):
                    framework = f" - {line.replace('**Framework:** ', '')}"
            entry_list.append(f"- {title} ({doc_type}{framework})")

        header = f"Found {len(results)} results for '{query}' (showing first 100):\n\n"
        footer = f"\n\nToo many results ({len(results)}). Consider refining your search or using list_entries() with filters."
        return header + "\n".join(entry_list) + footer


def extract_html_for_anchor(html: str, anchor: str):
    soup: bs4.Tag = bs4.BeautifulSoup(html)

    if target := (soup.find(id=anchor) or soup.find("a", attrs={"name": anchor})):
        # The target is typically an anchor or a heading. Move up to its container element for relevant context.
        target = target.parent or target

        if target.name == "dt":
            # We landed in a <dt> and need its following <dd> as well.
            for element in target.previous_siblings:
                element.decompose()
            while target.next_element:
                target = target.next_element
                if target.name == "dd":
                    for element in target.next_siblings:
                        element.decompose()
                    break
            soup = target.parent
        else:
            soup = target

    return soup.decode()


def infer_primary_language(config: ProcessedDocsetConfig) -> str:
    if primary := config.get("primary_language"):
        return primary
    language_names = config.get("languages", {}).keys()
    if language_names:
        return next(iter(language_names))
    # There was previously some code that attempted to infer language from the docset name,
    # but it didn't seem very effective.
    return config["name"]
