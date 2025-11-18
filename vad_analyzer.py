#!/usr/bin/env python3
"""
VAD Data Analyzer - CLI tool for querying and analyzing collected VAD data

Provides commands for:
- Querying metrics and exporting to CSV
- Statistical analysis
- Visualization
- Configuration recommendations
- Data cleanup
"""

import sys
import argparse
import csv
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from vad_database import VADDatabase
from vad_recommender import VADRecommender


class VADAnalyzer:
    """CLI analyzer for VAD data."""

    def __init__(self, db_path: str):
        """Initialize analyzer with database connection."""
        self.db = VADDatabase(db_path)

    def cmd_query(self, args):
        """Query and export metrics to CSV."""
        # Parse time arguments
        start_time = self._parse_time(args.start) if args.start else None
        end_time = self._parse_time(args.end) if args.end else None

        print(f"Querying data from {start_time or 'beginning'} to {end_time or 'present'}...")

        # Get metrics with tags
        metrics = self.db.get_metrics_with_tags(start_time, end_time)

        # Filter by tag if specified
        if args.tags:
            tag_filters = args.tags.split(',')
            metrics = [
                m for m in metrics
                if any(tag in m['active_tags'] for tag in tag_filters)
            ]

        print(f"Found {len(metrics)} matching records")

        # Export to CSV
        output_file = args.output or 'vad_data_export.csv'
        with open(output_file, 'w', newline='') as f:
            if metrics:
                fieldnames = ['timestamp', 'datetime', 'rms_level', 'is_speech', 'active_tags']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for m in metrics:
                    writer.writerow({
                        'timestamp': m['timestamp'],
                        'datetime': datetime.fromtimestamp(m['timestamp']).isoformat(),
                        'rms_level': round(m['rms_level'], 2),
                        'is_speech': m['is_speech'],
                        'active_tags': '|'.join(m['active_tags'])
                    })

        print(f"Data exported to: {output_file}")

    def cmd_stats(self, args):
        """Display database statistics."""
        print("Calculating statistics...\n")

        stats = self.db.get_statistics()

        print("=" * 70)
        print("VAD DATA STATISTICS")
        print("=" * 70)

        # Time range
        print(f"\nTime Range:")
        print(f"  Start:    {stats['time_range']['start']}")
        print(f"  End:      {stats['time_range']['end']}")
        print(f"  Duration: {stats['time_range']['duration_hours']:.2f} hours")

        # Metrics
        print(f"\nAudio Metrics:")
        print(f"  Total frames: {stats['metrics_count']:,}")
        print(f"  Speech frames: {stats['speech_statistics']['speech_frames']:,} ({stats['speech_statistics']['speech_ratio']}%)")
        print(f"  Silence frames: {stats['speech_statistics']['silence_frames']:,}")

        # RMS statistics
        print(f"\nRMS Level Statistics:")
        print(f"  Average: {stats['rms_statistics']['avg']}%")
        print(f"  Minimum: {stats['rms_statistics']['min']}%")
        print(f"  Maximum: {stats['rms_statistics']['max']}%")

        # Metadata
        print(f"\nMetadata Events:")
        print(f"  Total events: {stats['metadata_statistics']['event_count']}")
        print(f"  Unique tags: {stats['metadata_statistics']['unique_tags']}")
        if stats['metadata_statistics']['tag_distribution']:
            print(f"\n  Tag Distribution:")
            for tag, count in stats['metadata_statistics']['tag_distribution'].items():
                print(f"    {tag:30s}: {count:5d}")

        # Database
        print(f"\nDatabase:")
        print(f"  Size: {stats['database_size_mb']} MB")

        print("=" * 70)

    def cmd_visualize(self, args):
        """Generate visualizations."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from datetime import datetime
        except ImportError:
            print("ERROR: matplotlib is required for visualization")
            print("Install with: pip3 install matplotlib")
            sys.exit(1)

        # Parse time arguments
        start_time = self._parse_time(args.start) if args.start else None
        end_time = self._parse_time(args.end) if args.end else None

        print(f"Loading data from {start_time or 'beginning'} to {end_time or 'present'}...")

        # Limit query to reasonable size for visualization
        metrics = self.db.query_metrics(start_time, end_time, limit=10000)

        if not metrics:
            print("No data found for the specified time range")
            return

        print(f"Loaded {len(metrics)} records")

        # Prepare data
        timestamps = [datetime.fromtimestamp(m['timestamp']) for m in metrics]
        rms_levels = [m['rms_level'] for m in metrics]
        speech_flags = [m['is_speech'] for m in metrics]

        # Create figure with subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

        # Plot 1: RMS levels
        ax1.plot(timestamps, rms_levels, linewidth=0.5, color='blue', alpha=0.7)
        ax1.set_ylabel('RMS Level (%)', fontsize=12)
        ax1.set_title('Audio RMS Levels Over Time', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, max(rms_levels) * 1.1 if rms_levels else 100)

        # Plot 2: Speech detection
        speech_y = [1 if s else 0 for s in speech_flags]
        ax2.fill_between(timestamps, speech_y, color='green', alpha=0.5, label='Speech')
        ax2.set_ylabel('Speech Detection', fontsize=12)
        ax2.set_xlabel('Time', fontsize=12)
        ax2.set_title('VAD Speech Detection', fontsize=14, fontweight='bold')
        ax2.set_yticks([0, 1])
        ax2.set_yticklabels(['Silence', 'Speech'])
        ax2.grid(True, alpha=0.3)

        # Format x-axis
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45)

        plt.tight_layout()

        # Save figure
        output_file = args.output or 'vad_visualization.png'
        plt.savefig(output_file, dpi=150)
        print(f"\nVisualization saved to: {output_file}")

        if args.show:
            plt.show()

    def cmd_cleanup(self, args):
        """Clean up old data."""
        days = args.older_than

        print(f"Cleaning up data older than {days} days...")
        print("This operation cannot be undone!")

        if not args.yes:
            response = input("Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Cleanup cancelled")
                return

        metrics_deleted, events_deleted = self.db.cleanup_old_data(days)

        print(f"\nCleanup complete:")
        print(f"  Metrics deleted: {metrics_deleted:,}")
        print(f"  Events deleted: {events_deleted:,}")

    def cmd_recommend(self, args):
        """Generate configuration recommendations."""
        print("Analyzing collected data to generate recommendations...")
        print("This may take a few moments...\n")

        recommender = VADRecommender(self.db)
        recommendations = recommender.generate_recommendations()
        recommender.print_recommendations(recommendations)

    @staticmethod
    def _parse_time(time_str: str) -> Optional[float]:
        """
        Parse time string to Unix timestamp.

        Supports:
        - ISO format: 2025-01-15T10:30:00
        - Relative: -1h, -30m, -2d
        """
        if time_str.startswith('-'):
            # Relative time
            value = int(time_str[1:-1])
            unit = time_str[-1]

            if unit == 'h':
                delta = timedelta(hours=value)
            elif unit == 'm':
                delta = timedelta(minutes=value)
            elif unit == 'd':
                delta = timedelta(days=value)
            else:
                raise ValueError(f"Invalid time unit: {unit}")

            return (datetime.now() - delta).timestamp()
        else:
            # Absolute time (ISO format)
            dt = datetime.fromisoformat(time_str)
            return dt.timestamp()


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="VAD Data Analyzer - Query and analyze collected VAD data",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--db',
        default='/mnt/shared/raspi-audio/vad_data.db',
        help='Path to VAD database'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Query command
    query_parser = subparsers.add_parser('query', help='Query and export data to CSV')
    query_parser.add_argument('--start', help='Start time (ISO format or relative: -1h, -30m, -2d)')
    query_parser.add_argument('--end', help='End time (ISO format or relative)')
    query_parser.add_argument('--tags', help='Filter by tags (comma-separated)')
    query_parser.add_argument('--output', help='Output CSV file (default: vad_data_export.csv)')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Display database statistics')

    # Visualize command
    viz_parser = subparsers.add_parser('visualize', help='Generate visualizations')
    viz_parser.add_argument('--start', help='Start time (ISO format or relative)')
    viz_parser.add_argument('--end', help='End time (ISO format or relative)')
    viz_parser.add_argument('--output', help='Output image file (default: vad_visualization.png)')
    viz_parser.add_argument('--show', action='store_true', help='Display plot interactively')

    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Delete old data')
    cleanup_parser.add_argument('--older-than', type=int, required=True, help='Delete data older than N days')
    cleanup_parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')

    # Recommend command
    recommend_parser = subparsers.add_parser('recommend', help='Generate configuration recommendations')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize analyzer
    analyzer = VADAnalyzer(args.db)

    # Dispatch command
    if args.command == 'query':
        analyzer.cmd_query(args)
    elif args.command == 'stats':
        analyzer.cmd_stats(args)
    elif args.command == 'visualize':
        analyzer.cmd_visualize(args)
    elif args.command == 'cleanup':
        analyzer.cmd_cleanup(args)
    elif args.command == 'recommend':
        analyzer.cmd_recommend(args)

    analyzer.db.close()


if __name__ == '__main__':
    main()
