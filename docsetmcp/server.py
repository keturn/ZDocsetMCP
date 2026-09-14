"""
Dash MCP Server - Extract documentation from Dash docsets as Markdown
"""

import logging
import os
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
        self.docset_path: str | None = None
        if (from_env := os.getenv("DOCSET_PATH")) is not None:
            self.docset_path = os.path.expanduser(from_env)
            logger.debug("DOCSET_PATH set to %s", self.docset_path)
        else:
            logger.debug("DOCSET_PATH env not set. Checking default locations.")
            for p in self.parse_path_list(DEFAULT_DOCSET_PATHS):
                if Path(p).exists():
                    self.docset_path = p
                    logger.debug("defaulting to docset location %s", self.docset_path)
                    break
                else:
                    logger.debug("default location %s does not exist.", p)
        self.cheatsheet_path: str | None = None
        self.additional_docset_paths: list[str] = []
        self.additional_cheatsheet_paths: list[str] = []

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
