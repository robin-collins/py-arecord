"""
Metadata State Machine for VAD Data Collection

Manages timed and persistent metadata tags with conflict resolution.
"""

import time
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum


class TagType(Enum):
    """Available metadata tag types."""
    ONE_SPEAKER_CLOSE = "one_speaker_close"
    TWO_SPEAKERS = "two_speakers"
    MUSIC_PLAYING = "music_playing"
    VIDEO_PLAYING = "video_playing"
    LOUD_AMBIENT = "loud_ambient"


class DurationType(Enum):
    """Tag duration types."""
    TIMED_30S = "timed_30s"
    PERSISTENT = "persistent"


@dataclass
class ActiveTag:
    """Represents an active metadata tag."""
    tag_type: TagType
    duration_type: DurationType
    start_time: float
    end_time: Optional[float]  # None for persistent tags
    db_event_id: Optional[int]  # Database record ID


class MetadataStateMachine:
    """
    Manages metadata tags with timed and persistent modes.

    Handles:
    - Timed tags (30 seconds duration)
    - Persistent toggle tags (on until explicitly turned off)
    - Conflict resolution (new persistent tag deactivates old ones)
    """

    # Hotkey mapping
    HOTKEY_MAP = {
        '1': (TagType.ONE_SPEAKER_CLOSE, DurationType.TIMED_30S),
        '2': (TagType.TWO_SPEAKERS, DurationType.TIMED_30S),
        'q': (TagType.ONE_SPEAKER_CLOSE, DurationType.PERSISTENT),
        'w': (TagType.TWO_SPEAKERS, DurationType.PERSISTENT),
        '0': (TagType.MUSIC_PLAYING, DurationType.TIMED_30S),
        '9': (TagType.VIDEO_PLAYING, DurationType.TIMED_30S),
        '8': (TagType.LOUD_AMBIENT, DurationType.TIMED_30S),
        'p': (TagType.MUSIC_PLAYING, DurationType.PERSISTENT),
        'o': (TagType.VIDEO_PLAYING, DurationType.PERSISTENT),
        'i': (TagType.LOUD_AMBIENT, DurationType.PERSISTENT),
    }

    TIMED_DURATION = 30.0  # seconds

    def __init__(self):
        """Initialize the metadata state machine."""
        self.active_tags: Dict[TagType, ActiveTag] = {}
        self.logger = logging.getLogger(__name__)

    def process_hotkey(self, key: str, db_callback=None) -> Optional[str]:
        """
        Process a hotkey press and update active tags.

        Args:
            key: The pressed key character
            db_callback: Callback function(tag_type, duration_type, end_time) -> event_id
                        Called to log new tags to database

        Returns:
            Status message for display, or None if key not recognized
        """
        if key not in self.HOTKEY_MAP:
            return None

        tag_type, duration_type = self.HOTKEY_MAP[key]
        current_time = time.time()

        # Check if this tag is already active
        if tag_type in self.active_tags:
            active_tag = self.active_tags[tag_type]

            # Persistent tag toggle: turn off
            if duration_type == DurationType.PERSISTENT:
                return self._deactivate_tag(tag_type, current_time)
            else:
                # Timed tag: restart timer
                return self._restart_timed_tag(tag_type, current_time, db_callback)
        else:
            # Activate new tag
            return self._activate_tag(tag_type, duration_type, current_time, db_callback)

    def _activate_tag(self, tag_type: TagType, duration_type: DurationType,
                      current_time: float, db_callback=None) -> str:
        """Activate a new metadata tag."""
        # If activating a persistent tag, deactivate other persistent tags of different types
        if duration_type == DurationType.PERSISTENT:
            for existing_type, existing_tag in list(self.active_tags.items()):
                if (existing_tag.duration_type == DurationType.PERSISTENT and
                    existing_type != tag_type):
                    self._deactivate_tag(existing_type, current_time)

        # Calculate end time for timed tags
        end_time = current_time + self.TIMED_DURATION if duration_type == DurationType.TIMED_30S else None

        # Log to database
        db_event_id = None
        if db_callback:
            db_event_id = db_callback(tag_type.value, duration_type.value, end_time)

        # Store active tag
        self.active_tags[tag_type] = ActiveTag(
            tag_type=tag_type,
            duration_type=duration_type,
            start_time=current_time,
            end_time=end_time,
            db_event_id=db_event_id
        )

        mode_str = "30s" if duration_type == DurationType.TIMED_30S else "PERSISTENT"
        self.logger.info(f"Tag activated: {tag_type.value} ({mode_str})")

        return f"✓ {self._format_tag_name(tag_type)} [{mode_str}]"

    def _deactivate_tag(self, tag_type: TagType, current_time: float) -> str:
        """Deactivate an active tag."""
        if tag_type not in self.active_tags:
            return f"Tag {tag_type.value} not active"

        active_tag = self.active_tags[tag_type]

        # Update database with end time (handled externally via update_metadata_event_end_time)
        # This is done by the collector when it detects the tag was removed

        del self.active_tags[tag_type]
        self.logger.info(f"Tag deactivated: {tag_type.value}")

        return f"✗ {self._format_tag_name(tag_type)} OFF"

    def _restart_timed_tag(self, tag_type: TagType, current_time: float, db_callback=None) -> str:
        """Restart a timed tag (extends duration to 30s from now)."""
        # Remove old tag
        old_tag = self.active_tags[tag_type]
        del self.active_tags[tag_type]

        # Create new tag with fresh timer
        end_time = current_time + self.TIMED_DURATION

        db_event_id = None
        if db_callback:
            db_event_id = db_callback(tag_type.value, DurationType.TIMED_30S.value, end_time)

        self.active_tags[tag_type] = ActiveTag(
            tag_type=tag_type,
            duration_type=DurationType.TIMED_30S,
            start_time=current_time,
            end_time=end_time,
            db_event_id=db_event_id
        )

        self.logger.info(f"Timed tag restarted: {tag_type.value}")
        return f"↻ {self._format_tag_name(tag_type)} [30s restarted]"

    def update_and_get_active_tags(self, current_time: float) -> List[TagType]:
        """
        Update tag expirations and return currently active tags.

        Args:
            current_time: Current Unix timestamp

        Returns:
            List of currently active tag types
        """
        # Remove expired timed tags
        expired_tags = [
            tag_type for tag_type, tag in self.active_tags.items()
            if tag.end_time is not None and tag.end_time <= current_time
        ]

        for tag_type in expired_tags:
            self.logger.info(f"Timed tag expired: {tag_type.value}")
            del self.active_tags[tag_type]

        return list(self.active_tags.keys())

    def get_active_tags_display(self, current_time: float) -> str:
        """
        Get formatted string of active tags for terminal display.

        Args:
            current_time: Current Unix timestamp

        Returns:
            Formatted string showing active tags with remaining time
        """
        self.update_and_get_active_tags(current_time)

        if not self.active_tags:
            return "No active tags"

        display_parts = []
        for tag_type, tag in self.active_tags.items():
            if tag.duration_type == DurationType.PERSISTENT:
                display_parts.append(f"{self._format_tag_name(tag_type)} [PERSISTENT]")
            else:
                remaining = tag.end_time - current_time
                display_parts.append(f"{self._format_tag_name(tag_type)} [{int(remaining)}s]")

        return " | ".join(display_parts)

    def get_deactivated_tags(self, current_time: float) -> List[tuple]:
        """
        Get list of tags that just expired (for database updates).

        Returns:
            List of (tag_type, db_event_id, end_time) tuples
        """
        expired = []
        for tag_type, tag in list(self.active_tags.items()):
            if tag.end_time is not None and tag.end_time <= current_time:
                expired.append((tag_type, tag.db_event_id, tag.end_time))
                del self.active_tags[tag_type]
        return expired

    @staticmethod
    def _format_tag_name(tag_type: TagType) -> str:
        """Format tag type for display."""
        names = {
            TagType.ONE_SPEAKER_CLOSE: "1 Speaker Close",
            TagType.TWO_SPEAKERS: "2 Speakers",
            TagType.MUSIC_PLAYING: "Music",
            TagType.VIDEO_PLAYING: "Video",
            TagType.LOUD_AMBIENT: "Loud Ambient"
        }
        return names.get(tag_type, tag_type.value)
