"""Shared data structures passed between phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AssetKind(str, Enum):
    AUDIO_VIDEO = "audio_video"
    TEXT = "text"


@dataclass
class SourceAsset:
    """A single piece of content detected in the Drive source folder."""

    file_id: str
    name: str
    mime_type: str
    kind: AssetKind
    local_path: Optional[str] = None  # populated after download
    content_hash: Optional[str] = None  # for dedup (Future Improvement)


@dataclass
class CleanText:
    """Normalized text ready for transformation."""

    source: SourceAsset
    text: str
    word_count: int = 0

    def __post_init__(self) -> None:
        if not self.word_count:
            self.word_count = len(self.text.split())


@dataclass
class TransformOutput:
    """Drafts produced by the three Claude modules for one asset."""

    linkedin: str = ""
    x_thread: str = ""
    newsletter: str = ""
    errors: dict = field(default_factory=dict)  # module_name -> error string
