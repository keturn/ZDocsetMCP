from itertools import chain
from pathlib import Path

from docsetmcp.extractors.apple import AppleExtractor
from docsetmcp.extractors.base import DashExtractor
from docsetmcp.extractors.directory import FileSystemDirectoryExtractor
from docsetmcp.extractors.tarix import TarixExtractor
from docsetmcp.server import DocsetMCPConfig

EXTRACTORS: list[type[DashExtractor]] = [
    AppleExtractor,
    TarixExtractor,
    FileSystemDirectoryExtractor,
]


def construct(path: Path) -> DashExtractor:
    for extractor_class in EXTRACTORS:
        if extractor_class.is_format(path):
            return extractor_class(path)
    raise ValueError(f"No extractors matched ${path}")


def initialize_docsets(server_config: DocsetMCPConfig) -> dict[str, DashExtractor]:
    docset_locations = chain.from_iterable(
        p.rglob("*.docset") for p in server_config.get_docset_paths()
    )
    docset_locations = (p for p in docset_locations if p.is_dir())

    extractors = [construct(d) for d in docset_locations]

    return {e.id: e for e in extractors}
