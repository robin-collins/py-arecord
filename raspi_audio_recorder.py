#!/usr/bin/env python3
"""
Raspberry Pi Audio Recorder Service

Continuously records audio from ALSA device with silence-based segmentation.
Designed to run as a systemd daemon with robust error handling.
"""

import argparse
import configparser
import datetime
import logging
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import webrtcvad  # type: ignore
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    WEBRTCVAD_AVAILABLE = False


class AudioRecorder:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.recording_active = False
        self.shutdown_requested = False
        self.current_process: Optional[subprocess.Popen] = None
        self.overlap_buffer_path: Optional[str] = None
        self.temp_dir: Optional[Path] = None
        self.current_temp_files: set = set()

        self._setup_logging()
        self._setup_vad()
        self._validate_dependencies()
        self._validate_storage_path()

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from file."""
        config = configparser.ConfigParser()

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        config.read(config_path)

        return {
            "device": config.get("audio", "device", fallback="default"),
            "max_duration": config.getint(
                "recording", "max_duration_minutes", fallback=60
            ),
            "overlap_duration": config.getint(
                "recording", "overlap_minutes", fallback=5
            ),
            "storage_path": config.get(
                "storage", "directory", fallback="/mnt/shared/raspi-audio"
            ),
            "filename_prefix": config.get(
                "storage", "filename_prefix", fallback="audio"
            ),
            "silence_threshold": config.get(
                "audio", "silence_threshold", fallback="1%"
            ),
            "silence_duration": config.getfloat(
                "audio", "silence_duration_seconds", fallback=2.0
            ),
            "min_duration": config.getint(
                "recording", "min_duration_seconds", fallback=45
            ),
            "sample_rate": config.getint("audio", "sample_rate", fallback=16000),
            "channels": config.getint("audio", "channels", fallback=1),
            "compression_format": config.get(
                "audio", "compression_format", fallback="wav"
            ).lower(),
            "use_vad": config.getboolean("audio", "use_vad", fallback=True),
            "vad_aggressiveness": config.getint(
                "audio", "vad_aggressiveness", fallback=2
            ),
            "vad_frame_duration_ms": config.getint(
                "audio", "vad_frame_duration_ms", fallback=30
            ),
            "noise_floor_threshold": config.get(
                "audio", "noise_floor_threshold", fallback="1.0%"
            ),
            "log_level": config.get("logging", "level", fallback="INFO"),
        }

    def _setup_logging(self):
        """Configure logging for both console and systemd journal."""
        log_level = getattr(logging, self.config["log_level"].upper(), logging.INFO)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )

        self.logger = logging.getLogger("raspi_audio_recorder")
        self.logger.info("Audio recorder service initialized")

    def _setup_vad(self):
        """Initialize WebRTC VAD if enabled and available."""
        self.vad = None
        self.use_vad = self.config["use_vad"]
        
        if self.use_vad:
            if not WEBRTCVAD_AVAILABLE:
                self.logger.warning(
                    "WebRTC VAD requested but not available. "
                    "Install with: pip install webrtcvad. "
                    "Falling back to RMS-only detection."
                )
                self.use_vad = False
                return
            
            # Validate sample rate
            valid_sample_rates = [8000, 16000, 32000, 48000]
            sample_rate = self.config["sample_rate"]
            if sample_rate not in valid_sample_rates:
                self.logger.warning(
                    f"Sample rate {sample_rate} not supported by WebRTC VAD. "
                    f"Valid rates: {valid_sample_rates}. "
                    f"Falling back to RMS-only detection."
                )
                self.use_vad = False
                return
            
            # Validate frame duration
            valid_durations = [10, 20, 30]
            frame_duration = self.config["vad_frame_duration_ms"]
            if frame_duration not in valid_durations:
                self.logger.warning(
                    f"Frame duration {frame_duration}ms not supported by WebRTC VAD. "
                    f"Valid durations: {valid_durations}ms. Using 30ms."
                )
                self.config["vad_frame_duration_ms"] = 30
            
            # Validate aggressiveness
            aggressiveness = self.config["vad_aggressiveness"]
            if not 0 <= aggressiveness <= 3:
                self.logger.warning(
                    f"VAD aggressiveness {aggressiveness} out of range (0-3). Using 2."
                )
                self.config["vad_aggressiveness"] = 2
            
            try:
                self.vad = webrtcvad.Vad(self.config["vad_aggressiveness"])
                self.logger.info(
                    f"WebRTC VAD initialized: aggressiveness={self.config['vad_aggressiveness']}, "
                    f"frame_duration={self.config['vad_frame_duration_ms']}ms"
                )
            except Exception as e:
                self.logger.error(f"Failed to initialize WebRTC VAD: {e}")
                self.use_vad = False
        else:
            self.logger.info("WebRTC VAD disabled, using RMS-only detection")

    def _validate_dependencies(self):
        """Check for required external dependencies."""
        try:
            result = subprocess.run(
                ["sox", "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError("SoX not working properly")
            self.logger.info(
                f"SoX version check passed: {result.stdout.strip().split()[0]}"
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, RuntimeError) as e:
            self.logger.error(f"SoX dependency check failed: {e}")
            raise RuntimeError("SoX is required but not available or not working")

        try:
            result = subprocess.run(
                ["arecord", "--list-devices"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.logger.info("ALSA arecord available")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.logger.error(f"ALSA arecord check failed: {e}")
            raise RuntimeError("ALSA arecord is required but not available")

    def _validate_storage_path(self):
        """Validate storage directory exists and is writable."""
        storage_path = Path(self.config["storage_path"])
        self.temp_dir = storage_path / ".tmp"

        try:
            storage_path.mkdir(parents=True, exist_ok=True)
            self.temp_dir.mkdir(parents=True, exist_ok=True)

            test_file = storage_path / ".write_test"
            test_file.touch()
            test_file.unlink()

            temp_test_file = self.temp_dir / ".write_test"
            temp_test_file.touch()
            temp_test_file.unlink()

            self.logger.info(f"Storage path validated: {storage_path}")
            self.logger.info(f"Temp directory validated: {self.temp_dir}")
        except (OSError, PermissionError) as e:
            self.logger.error(f"Storage path validation failed: {e}")
            raise RuntimeError(f"Cannot write to storage directory: {storage_path}")

    def _generate_filename(self) -> tuple[str, str]:
        """Generate unique filename with UTC timestamp and sample rate.
        
        Returns:
            tuple: (temp_path, final_path) - paths for temporary and final storage
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        sample_rate_khz = self.config["sample_rate"] // 1000
        file_ext = self.config["compression_format"]
        prefix = self.config["filename_prefix"]
        base_name = (
            f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}_{sample_rate_khz}kHz.{file_ext}"
        )
        
        final_path = Path(self.config["storage_path"]) / base_name
        temp_path = self.temp_dir / base_name

        counter = 1
        while final_path.exists() or temp_path.exists():
            name_with_version = f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}_{sample_rate_khz}kHz_v{counter}.{file_ext}"
            final_path = Path(self.config["storage_path"]) / name_with_version
            temp_path = self.temp_dir / name_with_version
            counter += 1

        return str(temp_path), str(final_path)

    def _create_overlap_buffer(self, source_file: str) -> Optional[str]:
        """Create overlap buffer from the end of the previous recording."""
        if not os.path.exists(source_file):
            return None

        try:
            file_ext = self.config["compression_format"]
            overlap_path = self.temp_dir / f".overlap_buffer.{file_ext}"
            overlap_minutes = self.config["overlap_duration"]

            cmd = [
                "sox",
                source_file,
                str(overlap_path),
                "trim",
                f"-{overlap_minutes}:00",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                self.logger.info(f"Created overlap buffer: {overlap_minutes} minutes")
                self.current_temp_files.add(str(overlap_path))
                return str(overlap_path)
            else:
                self.logger.warning(f"Failed to create overlap buffer: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            self.logger.warning("Timeout creating overlap buffer")
            return None
        except Exception as e:
            self.logger.warning(f"Error creating overlap buffer: {e}")
            return None

    def _calculate_rms(self, audio_chunk: bytes) -> float:
        """Calculate RMS (Root Mean Square) audio level from PCM data."""
        if len(audio_chunk) == 0:
            return 0.0
        
        # S16_LE = signed 16-bit little-endian
        sample_count = len(audio_chunk) // 2
        if sample_count == 0:
            return 0.0
        
        # Unpack audio samples
        fmt = f"<{sample_count}h"  # little-endian signed shorts
        try:
            samples = struct.unpack(fmt, audio_chunk[:sample_count * 2])
            # Calculate RMS
            sum_squares = sum(sample ** 2 for sample in samples)
            rms = (sum_squares / sample_count) ** 0.5
            # Normalize to 0-100 scale (max value for 16-bit is 32768)
            return (rms / 32768.0) * 100.0
        except struct.error:
            return 0.0

    def _check_for_speech(self, audio_chunk: bytes, sample_rate: int) -> tuple[bool, float]:
        """
        Two-stage speech detection: RMS pre-filter + WebRTC VAD.
        
        Args:
            audio_chunk: Raw PCM audio data
            sample_rate: Audio sample rate
            
        Returns:
            tuple: (is_speech, rms_level)
        """
        # Stage 1: RMS pre-filter (cheap, filters absolute silence)
        rms = self._calculate_rms(audio_chunk)
        
        # Parse noise floor threshold
        noise_floor_str = self.config["noise_floor_threshold"].rstrip('%')
        noise_floor_percent = float(noise_floor_str)
        
        if rms < noise_floor_percent:
            # Definitely silence/noise floor - skip VAD processing
            return False, rms
        
        # Stage 2: WebRTC VAD (more expensive but accurate)
        if self.use_vad and self.vad:
            try:
                # VAD requires exact frame sizes
                is_speech = self.vad.is_speech(audio_chunk, sample_rate)
                return is_speech, rms
            except Exception as e:
                self.logger.debug(f"VAD error: {e}, falling back to RMS")
                # Fall back to RMS threshold if VAD fails
                silence_threshold_str = self.config["silence_threshold"].rstrip('%')
                silence_threshold_percent = float(silence_threshold_str)
                return rms >= silence_threshold_percent, rms
        else:
            # VAD disabled or unavailable, use RMS threshold
            silence_threshold_str = self.config["silence_threshold"].rstrip('%')
            silence_threshold_percent = float(silence_threshold_str)
            return rms >= silence_threshold_percent, rms

    def _record_segment(self, temp_file: str) -> bool:
        """Record a single audio segment with Python-based silence detection."""
        try:
            max_duration_seconds = self.config["max_duration"] * 60
            min_duration = self.config["min_duration"]
            sample_rate = self.config["sample_rate"]
            channels = self.config["channels"]
            silence_duration = self.config["silence_duration"]

            # Start arecord with leading silence detection to wait for sound
            arecord_cmd = [
                "arecord",
                "-D",
                self.config["device"],
                "-f",
                "S16_LE",
                "-c",
                str(channels),
                "-r",
                str(sample_rate),
                "-t",
                "raw",  # Raw PCM output for Python processing
            ]

            # SoX to write the file (without silence detection)
            sox_write_cmd = [
                "sox",
                "-t",
                "raw",
                "-r",
                str(sample_rate),
                "-c",
                str(channels),
                "-e",
                "signed",
                "-b",
                "16",
                "-",
                temp_file,
            ]

            if self.config["compression_format"] != "wav":
                sox_write_cmd.extend(["-C", "0"])

            detection_method = "WebRTC VAD + RMS" if self.use_vad else "RMS only"
            self.logger.info(f"Starting recording: {temp_file}")
            self.logger.info(
                f"Detection method: {detection_method}, "
                f"Minimum duration: {min_duration}s, "
                f"Silence duration: {silence_duration}s"
            )

            # Start processes
            arecord_proc = subprocess.Popen(
                arecord_cmd, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            sox_proc = subprocess.Popen(
                sox_write_cmd, 
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            self.current_process = arecord_proc
            self.recording_active = True

            start_time = time.time()
            silence_start_time = None
            
            # Calculate frame size for VAD (frame duration in samples)
            vad_frame_duration_ms = self.config["vad_frame_duration_ms"]
            vad_frame_size = (sample_rate * vad_frame_duration_ms // 1000) * channels * 2
            
            # Use VAD frame size if enabled, otherwise 1 second chunks
            chunk_size = vad_frame_size if self.use_vad else sample_rate * channels * 2
            sound_detected = False
            
            while self.recording_active and not self.shutdown_requested:
                elapsed_time = time.time() - start_time
                
                # Check if processes died
                if arecord_proc.poll() is not None:
                    self.logger.warning("arecord process terminated unexpectedly")
                    break
                
                # Emergency stop at maximum duration
                if elapsed_time >= max_duration_seconds:
                    self.logger.info(f"Maximum duration reached ({elapsed_time:.1f}s), stopping recording")
                    break

                # Read audio chunk
                try:
                    audio_chunk = arecord_proc.stdout.read(chunk_size)
                    if not audio_chunk or len(audio_chunk) < chunk_size:
                        # Incomplete chunk, might be end of stream
                        if audio_chunk and sox_proc.stdin:
                            sox_proc.stdin.write(audio_chunk)
                            sox_proc.stdin.flush()
                        break
                    
                    # Write to SoX
                    if sox_proc.stdin:
                        sox_proc.stdin.write(audio_chunk)
                        sox_proc.stdin.flush()
                    
                    # Wait for initial sound detection (leading silence skip)
                    if not sound_detected:
                        is_speech, rms = self._check_for_speech(audio_chunk, sample_rate)
                        if is_speech:
                            sound_detected = True
                            start_time = time.time()  # Reset timer when speech first detected
                            detection_type = "Speech" if self.use_vad else "Sound"
                            self.logger.info(
                                f"{detection_type} detected (RMS: {rms:.2f}%), starting recording timer"
                            )
                        continue
                    
                    # After sound detected, check timing and silence
                    elapsed_time = time.time() - start_time
                    
                    # Only check for silence after minimum duration
                    if elapsed_time >= min_duration:
                        is_speech, rms = self._check_for_speech(audio_chunk, sample_rate)
                        
                        if not is_speech:
                            # Silence/non-speech detected
                            if silence_start_time is None:
                                silence_start_time = time.time()
                                detection_type = "Non-speech" if self.use_vad else "Silence"
                                self.logger.debug(
                                    f"{detection_type} started at {elapsed_time:.1f}s (RMS: {rms:.2f}%)"
                                )
                            else:
                                silence_elapsed = time.time() - silence_start_time
                                if silence_elapsed >= silence_duration:
                                    detection_type = "non-speech" if self.use_vad else "silence"
                                    self.logger.info(
                                        f"Continuous {detection_type} threshold met "
                                        f"({silence_elapsed:.1f}s >= {silence_duration}s), "
                                        f"stopping recording at {elapsed_time:.1f}s"
                                    )
                                    break
                        else:
                            # Speech detected, reset silence timer
                            if silence_start_time is not None:
                                detection_type = "Speech" if self.use_vad else "Sound"
                                self.logger.debug(
                                    f"{detection_type} resumed at {elapsed_time:.1f}s (RMS: {rms:.2f}%)"
                                )
                            silence_start_time = None
                    
                except IOError as e:
                    self.logger.error(f"Error reading/writing audio data: {e}")
                    break

            # Clean shutdown
            if sox_proc.stdin:
                sox_proc.stdin.close()
            
            arecord_proc.terminate()
            sox_proc.terminate()

            try:
                arecord_proc.wait(timeout=5)
                sox_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                arecord_proc.kill()
                sox_proc.kill()

            self.recording_active = False
            self.current_process = None

            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 1000:
                duration = time.time() - start_time
                
                # Check if recording met minimum duration requirement
                if duration < min_duration:
                    self.logger.info(
                        f"Recording too short ({duration:.1f}s < {min_duration}s minimum), "
                        f"continuing to next segment"
                    )
                    os.remove(temp_file)
                    return False
                
                self.logger.info(
                    f"Recording completed: {temp_file} ({duration:.1f}s)"
                )
                self.current_temp_files.add(temp_file)
                return True
            else:
                self.logger.warning(
                    f"Recording file is empty or too small: {temp_file}"
                )
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return False

        except Exception as e:
            self.logger.error(f"Error during recording: {e}")
            self.recording_active = False
            self.current_process = None
            return False

    def _merge_with_overlap(self, overlap_file: str, new_file: str) -> str:
        """Merge overlap buffer with new recording."""
        try:
            file_ext = self.config["compression_format"]
            merged_file = new_file.replace(f".{file_ext}", f"_merged.{file_ext}")

            cmd = ["sox", overlap_file, new_file, merged_file]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                os.remove(new_file)
                os.rename(merged_file, new_file)
                self.logger.info("Successfully merged overlap with new recording")
                return new_file
            else:
                self.logger.warning(f"Failed to merge overlap: {result.stderr}")
                return new_file
        except Exception as e:
            self.logger.warning(f"Error merging overlap: {e}")
            return new_file
    
    def _move_to_final(self, temp_file: str, final_file: str) -> bool:
        """Move completed recording from temp to final directory."""
        try:
            import shutil
            shutil.move(temp_file, final_file)
            self.current_temp_files.discard(temp_file)
            self.logger.info(f"Moved recording to final location: {final_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to move recording to final location: {e}")
            return False
    
    def _cleanup_temp_files(self):
        """Clean up temporary files on shutdown."""
        for temp_file in list(self.current_temp_files):
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    self.logger.info(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                self.logger.warning(f"Failed to clean up temp file {temp_file}: {e}")
        self.current_temp_files.clear()

    def _signal_handler(self, signum, _frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown")
        self.shutdown_requested = True
        self.recording_active = False

        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
        
        self._cleanup_temp_files()

    def run(self):
        """Main recording loop."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("Starting continuous audio recording service")
        self.logger.info(
            f"Device: {self.config['device']}, Storage: {self.config['storage_path']}"
        )

        last_recording_file = None

        while not self.shutdown_requested:
            try:
                temp_file, final_file = self._generate_filename()

                if self._record_segment(temp_file):
                    if last_recording_file and self.overlap_buffer_path:
                        temp_file = self._merge_with_overlap(
                            self.overlap_buffer_path, temp_file
                        )

                    if self.overlap_buffer_path:
                        try:
                            os.remove(self.overlap_buffer_path)
                            self.current_temp_files.discard(self.overlap_buffer_path)
                        except OSError:
                            pass

                    if self._move_to_final(temp_file, final_file):
                        self.overlap_buffer_path = self._create_overlap_buffer(final_file)
                        last_recording_file = final_file
                    else:
                        self.logger.warning("Failed to move recording to final location")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                            self.current_temp_files.discard(temp_file)
                else:
                    # Recording didn't meet minimum duration or failed
                    # Continue immediately to next recording attempt
                    # (SoX will wait for sound via leading silence detection)
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(10)

        if self.overlap_buffer_path and os.path.exists(self.overlap_buffer_path):
            try:
                os.remove(self.overlap_buffer_path)
                self.current_temp_files.discard(self.overlap_buffer_path)
            except OSError:
                pass
        
        self._cleanup_temp_files()
        self.logger.info("Audio recording service stopped")


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi Audio Recorder Service")
    parser.add_argument(
        "--config",
        "-c",
        default="config.ini",
        help="Path to configuration file (default: config.ini)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration and dependencies, then exit",
    )

    args = parser.parse_args()

    try:
        recorder = AudioRecorder(args.config)

        if args.validate:
            print("Configuration and dependencies validated successfully")
            return 0

        recorder.run()
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
