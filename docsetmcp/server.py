"""
Dash MCP Server - Extract documentation from Dash docsets as Markdown
"""

import logging
import os
from itertools import chain
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

DEFAULT_DOCSET_PATHS = [
    "~/Library/Application Support/Dash/DocSets",  # Dash on macOS
    "~/.var/app/org.zealdocs.Zeal/data/Zeal/Zeal/docsets",  # Zeal Flatpak on Linux
]

logger = logging.getLogger(__name__)


# Global configuration class to hold runtime settings
class DocsetMCPConfig:
    def __init__(self):
        # I think the reason there's both a single `docset_path` and an `additional` list is so that the CLI
        # can override the default if it wants to, but also supplement while keeping the default intact.
        self.docset_path: Path | None = None
        if (from_env := os.getenv("DOCSET_PATH")) is not None:
            self.set_docset_path(from_env)
            logger.debug("DOCSET_PATH set to %s", self.docset_path)
        else:
            logger.debug("DOCSET_PATH env not set. Checking default locations.")
            for p in DEFAULT_DOCSET_PATHS:
                if Path(p).expanduser().exists():
                    self.set_docset_path(p)
                    logger.debug("defaulting to docset location %s", self.docset_path)
                    break
                else:
                    logger.debug("default location %s does not exist.", p)
        self.cheatsheet_path: str | None = None
        self.additional_docset_paths: list[Path] = []
        self.additional_cheatsheet_paths: list[str] = []

    def get_docset_paths(self) -> list[Path]:
        paths = []
        if self.docset_path is not None:
            paths.append(Path(self.docset_path))
        paths.extend(self.additional_docset_paths)
        return [p.absolute() for p in paths]

    def set_docset_path(self, path_str: str):
        self.docset_path = Path(path_str).expanduser()

    def set_additional_docset_paths(self, input_strings: list[str]):
        path_strings = chain.from_iterable(s.split(os.pathsep) for s in input_strings)
        self.additional_docset_paths[:] = [Path(p).expanduser() for p in path_strings]

    def parse_path_list(self, value: str | list[str] | None) -> list[str]:
        """Parse path list from various input formats"""
        if not value:
            return []
        if isinstance(value, list):
            return [os.path.expanduser(p) for p in value if p.strip()]
        # Must be str at this point since we've ruled out None and list
        return [os.path.expanduser(p.strip()) for p in value.split(":") if p.strip()]


# Global config instance
docsetmcp_config = DocsetMCPConfig()

from docsetmcp.cheatsheet_extractor import CheatsheetExtractor
from docsetmcp.dash_extractor import DashExtractor, initialize_docsets

# Initialize extractors for available docsets (will be populated by initialize_extractors)
extractors: dict[str, DashExtractor] = {}

# Initialize cheatsheet extractors (will be populated as needed)
cheatsheet_extractors: dict[str, CheatsheetExtractor] = {}


def initialize_extractors():
    """Initialize extractors with current configuration"""
    extractors.clear()
    extractors.update(initialize_docsets(docsetmcp_config))

    # TODO: cheatsheets


@lifespan
async def app_lifespan(_server: FastMCP):
    initialize_extractors()
    yield {"extractors": extractors}


# Create MCP server
mcp = FastMCP("Dash", lifespan=app_lifespan)
