"""
VAD Data Collection Database Schema and Operations

This module provides SQLite database operations for storing and querying
Voice Activity Detection metrics and metadata events.

Schema:
- audio_metrics: High-frequency VAD metrics (RMS, speech detection)
- metadata_events: User-tagged contextual metadata with time ranges
"""

import sqlite3
import logging
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timedelta
import time


class VADDatabase:
    """
    SQLite database manager for VAD data collection.

    Handles schema creation, data insertion, queries, and retention cleanup.
    """

    def __init__(self, db_path: str, retention_days: Optional[int] = None):
        """
        Initialize database connection and ensure schema exists.

        Args:
            db_path: Path to SQLite database file
            retention_days: Number of days to retain data (None = keep all)
        """
        self.db_path = db_path
        self.retention_days = retention_days
        self.logger = logging.getLogger(__name__)

        # Connect with optimizations for batch writes
        self.conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level='DEFERRED'
        )
        self.conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging for better concurrency
        self.conn.execute('PRAGMA synchronous=NORMAL')  # Balance safety and performance

        self._create_schema()
        self.logger.info(f"VAD database initialized: {db_path}")
        if retention_days:
            self.logger.info(f"Data retention policy: {retention_days} days")

    def _create_schema(self):
        """Create database tables and indexes if they don't exist."""
        cursor = self.conn.cursor()

        # Audio metrics table - high frequency data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audio_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                rms_level REAL NOT NULL,
                is_speech INTEGER NOT NULL,
                audio_chunk BLOB
            )
        ''')

        # Metadata events table - user-tagged contexts
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time REAL NOT NULL,
                end_time REAL,
                tag_type TEXT NOT NULL,
                duration_type TEXT NOT NULL,
                CHECK (duration_type IN ('timed_30s', 'persistent'))
            )
        ''')

        # Indexes for fast time-range queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_metrics_time
            ON audio_metrics(timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_events_time
            ON metadata_events(start_time, end_time)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_events_tag
            ON metadata_events(tag_type)
        ''')

        self.conn.commit()
        self.logger.debug("Database schema verified/created")

    def insert_audio_metrics_batch(self, metrics: List[Tuple[float, float, bool, Optional[bytes]]]):
        """
        Insert multiple audio metrics records in a single transaction.

        Args:
            metrics: List of (timestamp, rms_level, is_speech, audio_chunk) tuples
        """
        cursor = self.conn.cursor()
        cursor.executemany(
            'INSERT INTO audio_metrics (timestamp, rms_level, is_speech, audio_chunk) VALUES (?, ?, ?, ?)',
            metrics
        )
        self.conn.commit()

    def insert_metadata_event(self, start_time: float, tag_type: str, duration_type: str, end_time: Optional[float] = None):
        """
        Insert a metadata event record.

        Args:
            start_time: Unix timestamp when tag was activated
            tag_type: Type of tag (e.g., 'one_speaker_close', 'music_playing')
            duration_type: 'timed_30s' or 'persistent'
            end_time: Unix timestamp when tag ended (None for active persistent tags)
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO metadata_events (start_time, end_time, tag_type, duration_type) VALUES (?, ?, ?, ?)',
            (start_time, end_time, tag_type, duration_type)
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_metadata_event_end_time(self, event_id: int, end_time: float):
        """
        Update the end time of a metadata event (e.g., when stopping a persistent tag).

        Args:
            event_id: Database ID of the event
            end_time: Unix timestamp when tag ended
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE metadata_events SET end_time = ? WHERE id = ?',
            (end_time, event_id)
        )
        self.conn.commit()

    def query_metrics(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query audio metrics within a time range.

        Args:
            start_time: Unix timestamp (None = from beginning)
            end_time: Unix timestamp (None = to present)
            limit: Maximum number of records to return

        Returns:
            List of metric dictionaries with keys: timestamp, rms_level, is_speech
        """
        cursor = self.conn.cursor()

        query = 'SELECT timestamp, rms_level, is_speech FROM audio_metrics WHERE 1=1'
        params = []

        if start_time is not None:
            query += ' AND timestamp >= ?'
            params.append(start_time)

        if end_time is not None:
            query += ' AND timestamp <= ?'
            params.append(end_time)

        query += ' ORDER BY timestamp ASC'

        if limit:
            query += ' LIMIT ?'
            params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                'timestamp': row[0],
                'rms_level': row[1],
                'is_speech': bool(row[2])
            }
            for row in rows
        ]

    def query_metadata_events(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        tag_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query metadata events within a time range.

        Args:
            start_time: Unix timestamp (None = from beginning)
            end_time: Unix timestamp (None = to present)
            tag_type: Filter by specific tag type (None = all tags)

        Returns:
            List of event dictionaries
        """
        cursor = self.conn.cursor()

        query = 'SELECT id, start_time, end_time, tag_type, duration_type FROM metadata_events WHERE 1=1'
        params = []

        if start_time is not None:
            query += ' AND (end_time IS NULL OR end_time >= ?)'
            params.append(start_time)

        if end_time is not None:
            query += ' AND start_time <= ?'
            params.append(end_time)

        if tag_type:
            query += ' AND tag_type = ?'
            params.append(tag_type)

        query += ' ORDER BY start_time ASC'

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                'id': row[0],
                'start_time': row[1],
                'end_time': row[2],
                'tag_type': row[3],
                'duration_type': row[4]
            }
            for row in rows
        ]

    def get_metrics_with_tags(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Query audio metrics joined with active metadata tags.

        Args:
            start_time: Unix timestamp (None = from beginning)
            end_time: Unix timestamp (None = to present)

        Returns:
            List of metrics with 'active_tags' field containing list of tag types
        """
        metrics = self.query_metrics(start_time, end_time)
        events = self.query_metadata_events(start_time, end_time)

        # Build time-based index of active tags
        result = []
        for metric in metrics:
            metric_time = metric['timestamp']
            active_tags = [
                event['tag_type']
                for event in events
                if event['start_time'] <= metric_time and
                   (event['end_time'] is None or event['end_time'] >= metric_time)
            ]
            metric['active_tags'] = active_tags
            result.append(metric)

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """
        Calculate database statistics for overview and diagnostics.

        Returns:
            Dictionary with count, time range, and summary statistics
        """
        cursor = self.conn.cursor()

        # Metrics statistics
        cursor.execute('SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM audio_metrics')
        metrics_count, min_time, max_time = cursor.fetchone()

        cursor.execute('SELECT AVG(rms_level), MIN(rms_level), MAX(rms_level) FROM audio_metrics')
        avg_rms, min_rms, max_rms = cursor.fetchone()

        cursor.execute('SELECT COUNT(*) FROM audio_metrics WHERE is_speech = 1')
        speech_count = cursor.fetchone()[0]

        # Metadata statistics
        cursor.execute('SELECT COUNT(*), COUNT(DISTINCT tag_type) FROM metadata_events')
        event_count, unique_tags = cursor.fetchone()

        cursor.execute('SELECT tag_type, COUNT(*) as count FROM metadata_events GROUP BY tag_type ORDER BY count DESC')
        tag_distribution = {row[0]: row[1] for row in cursor.fetchall()}

        # Database file size
        cursor.execute('SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()')
        db_size_bytes = cursor.fetchone()[0]

        return {
            'metrics_count': metrics_count,
            'time_range': {
                'start': datetime.fromtimestamp(min_time).isoformat() if min_time else None,
                'end': datetime.fromtimestamp(max_time).isoformat() if max_time else None,
                'duration_hours': (max_time - min_time) / 3600 if min_time and max_time else 0
            },
            'rms_statistics': {
                'avg': round(avg_rms, 2) if avg_rms else 0,
                'min': round(min_rms, 2) if min_rms else 0,
                'max': round(max_rms, 2) if max_rms else 0
            },
            'speech_statistics': {
                'speech_frames': speech_count,
                'silence_frames': metrics_count - speech_count if metrics_count else 0,
                'speech_ratio': round(speech_count / metrics_count * 100, 2) if metrics_count else 0
            },
            'metadata_statistics': {
                'event_count': event_count,
                'unique_tags': unique_tags,
                'tag_distribution': tag_distribution
            },
            'database_size_mb': round(db_size_bytes / 1024 / 1024, 2)
        }

    def cleanup_old_data(self, days: Optional[int] = None) -> Tuple[int, int]:
        """
        Delete data older than specified number of days.

        Args:
            days: Number of days to retain (uses self.retention_days if None)

        Returns:
            Tuple of (metrics_deleted, events_deleted)
        """
        if days is None:
            days = self.retention_days

        if days is None:
            self.logger.warning("No retention period specified, skipping cleanup")
            return (0, 0)

        cutoff_time = time.time() - (days * 24 * 3600)
        cursor = self.conn.cursor()

        # Delete old metrics
        cursor.execute('DELETE FROM audio_metrics WHERE timestamp < ?', (cutoff_time,))
        metrics_deleted = cursor.rowcount

        # Delete old events
        cursor.execute('DELETE FROM metadata_events WHERE start_time < ?', (cutoff_time,))
        events_deleted = cursor.rowcount

        self.conn.commit()

        # Vacuum to reclaim space
        self.conn.execute('VACUUM')

        self.logger.info(f"Cleanup: deleted {metrics_deleted} metrics and {events_deleted} events older than {days} days")
        return (metrics_deleted, events_deleted)

    def close(self):
        """Close database connection."""
        self.conn.close()
        self.logger.info("Database connection closed")
