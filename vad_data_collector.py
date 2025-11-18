#!/usr/bin/env python3
"""
VAD Data Collector - Real-time audio metrics and metadata logging

Captures VAD metrics and user-tagged metadata for tuning optimization.
Runs as standalone application alongside the main audio recorder.
"""

import sys
import os
import subprocess
import signal
import time
import logging
import configparser
import struct
import threading
from typing import Optional, List, Tuple

# Import collector modules
from vad_database import VADDatabase
from vad_metadata import MetadataStateMachine
from vad_hotkeys import HotkeyHandler, print_hotkey_help


class VADDataCollector:
    """
    Main data collector application.

    Captures audio from ALSA, runs VAD detection, logs metrics to database,
    and handles hotkey-based metadata tagging.
    """

    def __init__(self, config_path: str = "vad_collector_config.ini"):
        """Initialize data collector with configuration."""
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()

        self.logger = logging.getLogger(__name__)
        self.logger.info("VAD Data Collector starting...")

        # Initialize components
        self.db = VADDatabase(
            db_path=self.config['database']['db_path'],
            retention_days=self.config['database'].get('retention_days')
        )
        self.metadata = MetadataStateMachine()

        # VAD initialization
        self.vad = None
        self.use_vad = self.config['vad']['use_vad']
        if self.use_vad:
            self._setup_vad()

        # Audio parameters
        self.sample_rate = self.config['audio']['sample_rate']
        self.channels = self.config['audio']['channels']
        self.vad_frame_duration_ms = self.config['vad']['vad_frame_duration_ms']
        self.vad_frame_size = self._calculate_frame_size()

        # Batch collection
        self.metrics_batch: List[Tuple] = []
        self.batch_interval = self.config['database']['batch_interval']
        self.last_batch_time = time.time()

        # Control flags
        self.running = False
        self.arecord_process: Optional[subprocess.Popen] = None

        # Statistics
        self.frames_processed = 0
        self.start_time = time.time()

    def _load_config(self) -> dict:
        """Load and parse configuration file."""
        parser = configparser.ConfigParser()

        if not os.path.exists(self.config_path):
            print(f"ERROR: Config file not found: {self.config_path}")
            sys.exit(1)

        parser.read(self.config_path)

        config = {
            'audio': {
                'device': parser.get('audio', 'device'),
                'sample_rate': parser.getint('audio', 'sample_rate'),
                'channels': parser.getint('audio', 'channels'),
                'format': parser.get('audio', 'format'),
            },
            'vad': {
                'use_vad': parser.getboolean('vad', 'use_vad'),
                'vad_aggressiveness': parser.getint('vad', 'vad_aggressiveness'),
                'vad_frame_duration_ms': parser.getint('vad', 'vad_frame_duration_ms'),
                'noise_floor_threshold': parser.getfloat('vad', 'noise_floor_threshold'),
                'silence_threshold': parser.getfloat('vad', 'silence_threshold'),
            },
            'database': {
                'db_path': parser.get('database', 'db_path'),
                'retention_days': parser.getint('database', 'retention_days') or None,
                'batch_interval': parser.getfloat('database', 'batch_interval'),
            },
            'storage': {
                'store_audio_chunks': parser.getboolean('storage', 'store_audio_chunks'),
            },
            'logging': {
                'log_level': parser.get('logging', 'log_level'),
                'log_file': parser.get('logging', 'log_file', fallback=None),
            },
            'display': {
                'status_update_interval': parser.getfloat('display', 'status_update_interval'),
                'show_detailed_metrics': parser.getboolean('display', 'show_detailed_metrics'),
            }
        }

        return config

    def _setup_logging(self):
        """Configure logging system."""
        log_level = getattr(logging, self.config['logging']['log_level'].upper())
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        handlers = [logging.StreamHandler()]
        if self.config['logging']['log_file']:
            handlers.append(logging.FileHandler(self.config['logging']['log_file']))

        logging.basicConfig(
            level=log_level,
            format=log_format,
            handlers=handlers
        )

    def _setup_vad(self):
        """Initialize WebRTC VAD."""
        try:
            import webrtcvad
            self.vad = webrtcvad.Vad(self.config['vad']['vad_aggressiveness'])
            self.logger.info(f"WebRTC VAD initialized (aggressiveness: {self.config['vad']['vad_aggressiveness']})")
        except ImportError:
            self.logger.warning("webrtcvad module not available, falling back to RMS-only")
            self.use_vad = False
        except Exception as e:
            self.logger.error(f"Failed to initialize VAD: {e}")
            self.use_vad = False

    def _calculate_frame_size(self) -> int:
        """Calculate VAD frame size in bytes."""
        frame_size = (self.sample_rate * self.vad_frame_duration_ms // 1000) * self.channels * 2
        if frame_size % 2 != 0:
            self.logger.warning(f"Frame size {frame_size} is odd, rounding down")
            frame_size -= 1
        return frame_size

    def _calculate_rms(self, audio_data: bytes) -> float:
        """
        Calculate RMS level from audio data.

        Args:
            audio_data: Raw PCM audio bytes (S16_LE format)

        Returns:
            RMS level as percentage (0-100)
        """
        if len(audio_data) < 2:
            return 0.0

        try:
            # Unpack signed 16-bit samples
            samples = struct.unpack(f'<{len(audio_data) // 2}h', audio_data)
            # Calculate RMS
            sum_squares = sum(s * s for s in samples)
            rms = (sum_squares / len(samples)) ** 0.5
            # Normalize to percentage (16-bit range is -32768 to 32767)
            return (rms / 32768.0) * 100.0
        except struct.error as e:
            self.logger.error(f"Error unpacking audio data: {e}")
            return 0.0

    def _check_for_speech(self, audio_data: bytes, rms_level: float) -> bool:
        """
        Determine if audio chunk contains speech.

        Args:
            audio_data: Raw PCM audio bytes
            rms_level: Pre-calculated RMS level

        Returns:
            True if speech detected, False otherwise
        """
        # Stage 1: RMS pre-filter
        if rms_level < self.config['vad']['noise_floor_threshold']:
            return False

        # Stage 2: WebRTC VAD (if available)
        if self.use_vad and self.vad:
            try:
                return self.vad.is_speech(audio_data, self.sample_rate)
            except Exception as e:
                self.logger.error(f"VAD processing error: {e}")
                # Fallback to RMS threshold
                return rms_level >= self.config['vad']['silence_threshold']
        else:
            # RMS-only fallback
            return rms_level >= self.config['vad']['silence_threshold']

    def _start_audio_capture(self):
        """Start arecord subprocess for audio capture."""
        cmd = [
            'arecord',
            '-D', self.config['audio']['device'],
            '-f', self.config['audio']['format'],
            '-r', str(self.sample_rate),
            '-c', str(self.channels),
            '-t', 'raw',
        ]

        self.logger.info(f"Starting audio capture: {' '.join(cmd)}")

        try:
            self.arecord_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.vad_frame_size * 10
            )
            self.logger.info("Audio capture started successfully")
        except Exception as e:
            self.logger.error(f"Failed to start arecord: {e}")
            raise

    def _stop_audio_capture(self):
        """Stop arecord subprocess gracefully."""
        if self.arecord_process:
            self.logger.info("Stopping audio capture...")
            self.arecord_process.terminate()
            try:
                self.arecord_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.logger.warning("arecord did not terminate, killing...")
                self.arecord_process.kill()
            self.arecord_process = None

    def _db_callback(self, tag_type: str, duration_type: str, end_time: Optional[float]) -> int:
        """Callback for metadata state machine to log events to database."""
        return self.db.insert_metadata_event(time.time(), tag_type, duration_type, end_time)

    def _flush_metrics_batch(self):
        """Flush accumulated metrics to database."""
        if self.metrics_batch:
            self.db.insert_audio_metrics_batch(self.metrics_batch)
            self.metrics_batch.clear()
            self.last_batch_time = time.time()

    def run(self):
        """Main collection loop with hotkey handling."""
        self.running = True
        self._start_audio_capture()

        print_hotkey_help()
        print("\nData collection started. Press keys to tag audio conditions.")
        print("=" * 64)

        last_status_update = time.time()

        try:
            with HotkeyHandler() as hotkey_handler:
                while self.running:
                    current_time = time.time()

                    # Check for hotkey input (non-blocking)
                    key = hotkey_handler.get_key(timeout=0.01)
                    if key:
                        if key == 'h':
                            print_hotkey_help()
                        else:
                            result = self.metadata.process_hotkey(key, self._db_callback)
                            if result:
                                print(f"\n{result}")

                    # Read audio frame
                    audio_chunk = self.arecord_process.stdout.read(self.vad_frame_size)
                    if not audio_chunk or len(audio_chunk) != self.vad_frame_size:
                        self.logger.warning("Incomplete audio frame, skipping")
                        continue

                    # Calculate metrics
                    rms_level = self._calculate_rms(audio_chunk)
                    is_speech = self._check_for_speech(audio_chunk, rms_level)

                    # Store audio chunk if configured
                    audio_blob = audio_chunk if self.config['storage']['store_audio_chunks'] else None

                    # Add to batch
                    self.metrics_batch.append((current_time, rms_level, int(is_speech), audio_blob))
                    self.frames_processed += 1

                    # Flush batch periodically
                    if current_time - self.last_batch_time >= self.batch_interval:
                        self._flush_metrics_batch()

                    # Update terminal display
                    if current_time - last_status_update >= self.config['display']['status_update_interval']:
                        self._print_status(current_time, rms_level, is_speech)
                        last_status_update = current_time

                    # Update metadata expiration
                    expired_tags = self.metadata.get_deactivated_tags(current_time)
                    for tag_type, db_event_id, end_time in expired_tags:
                        if db_event_id:
                            self.db.update_metadata_event_end_time(db_event_id, end_time)

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal")
        finally:
            self.shutdown()

    def _print_status(self, current_time: float, rms_level: float, is_speech: bool):
        """Print status line to terminal."""
        uptime = current_time - self.start_time
        fps = self.frames_processed / uptime if uptime > 0 else 0

        speech_indicator = "🔊 SPEECH" if is_speech else "🔇 silence"
        active_tags = self.metadata.get_active_tags_display(current_time)

        if self.config['display']['show_detailed_metrics']:
            print(f"\r{speech_indicator} | RMS: {rms_level:5.2f}% | FPS: {fps:5.1f} | Tags: {active_tags}",
                  end='', flush=True)
        else:
            print(f"\r{speech_indicator} | Tags: {active_tags}", end='', flush=True)

    def shutdown(self):
        """Graceful shutdown."""
        self.running = False
        print("\n\nShutting down...")

        # Flush remaining metrics
        self._flush_metrics_batch()

        # Stop audio capture
        self._stop_audio_capture()

        # Close database
        self.db.close()

        self.logger.info(f"Collection complete: {self.frames_processed} frames processed")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="VAD Data Collector")
    parser.add_argument(
        '--config',
        default='vad_collector_config.ini',
        help='Path to configuration file'
    )
    args = parser.parse_args()

    collector = VADDataCollector(config_path=args.config)

    # Handle signals
    def signal_handler(sig, frame):
        collector.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    collector.run()


if __name__ == '__main__':
    main()
