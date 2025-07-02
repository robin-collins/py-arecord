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
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any


class AudioRecorder:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.recording_active = False
        self.shutdown_requested = False
        self.current_process: Optional[subprocess.Popen] = None
        self.overlap_buffer_path: Optional[str] = None
        
        self._setup_logging()
        self._validate_dependencies()
        self._validate_storage_path()
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from file."""
        config = configparser.ConfigParser()
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
            
        config.read(config_path)
        
        return {
            'device': config.get('audio', 'device', fallback='default'),
            'max_duration': config.getint('recording', 'max_duration_minutes', fallback=60),
            'overlap_duration': config.getint('recording', 'overlap_minutes', fallback=5),
            'storage_path': config.get('storage', 'directory', fallback='/mnt/shared/raspi-audio'),
            'silence_threshold': config.get('audio', 'silence_threshold', fallback='1%'),
            'silence_duration': config.getfloat('audio', 'silence_duration_seconds', fallback=2.0),
            'sample_rate': config.getint('audio', 'sample_rate', fallback=44100),
            'channels': config.getint('audio', 'channels', fallback=1),
            'compression_format': config.get('audio', 'compression_format', fallback='wav').lower(),
            'log_level': config.get('logging', 'level', fallback='INFO')
        }
    
    def _setup_logging(self):
        """Configure logging for both console and systemd journal."""
        log_level = getattr(logging, self.config['log_level'].upper(), logging.INFO)
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger('raspi_audio_recorder')
        self.logger.info("Audio recorder service initialized")
    
    def _validate_dependencies(self):
        """Check for required external dependencies."""
        try:
            result = subprocess.run(['sox', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise RuntimeError("SoX not working properly")
            self.logger.info(f"SoX version check passed: {result.stdout.strip().split()[0]}")
        except (subprocess.TimeoutExpired, FileNotFoundError, RuntimeError) as e:
            self.logger.error(f"SoX dependency check failed: {e}")
            raise RuntimeError("SoX is required but not available or not working")
        
        try:
            result = subprocess.run(['arecord', '--list-devices'], 
                                  capture_output=True, text=True, timeout=10)
            self.logger.info("ALSA arecord available")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.logger.error(f"ALSA arecord check failed: {e}")
            raise RuntimeError("ALSA arecord is required but not available")
    
    def _validate_storage_path(self):
        """Validate storage directory exists and is writable."""
        storage_path = Path(self.config['storage_path'])
        
        try:
            storage_path.mkdir(parents=True, exist_ok=True)
            
            test_file = storage_path / '.write_test'
            test_file.touch()
            test_file.unlink()
            
            self.logger.info(f"Storage path validated: {storage_path}")
        except (OSError, PermissionError) as e:
            self.logger.error(f"Storage path validation failed: {e}")
            raise RuntimeError(f"Cannot write to storage directory: {storage_path}")
    
    def _generate_filename(self) -> str:
        """Generate unique filename with UTC timestamp and sample rate."""
        now = datetime.datetime.utcnow()
        sample_rate_khz = self.config['sample_rate'] // 1000
        file_ext = self.config['compression_format']
        base_name = f"audio_{now.strftime('%Y%m%d_%H%M%S')}_{sample_rate_khz}kHz.{file_ext}"
        full_path = Path(self.config['storage_path']) / base_name
        
        counter = 1
        while full_path.exists():
            name_with_version = f"audio_{now.strftime('%Y%m%d_%H%M%S')}_{sample_rate_khz}kHz_v{counter}.{file_ext}"
            full_path = Path(self.config['storage_path']) / name_with_version
            counter += 1
        
        return str(full_path)
    
    def _create_overlap_buffer(self, source_file: str) -> Optional[str]:
        """Create overlap buffer from the end of the previous recording."""
        if not os.path.exists(source_file):
            return None
            
        try:
            file_ext = self.config['compression_format']
            overlap_path = Path(self.config['storage_path']) / f'.overlap_buffer.{file_ext}'
            overlap_minutes = self.config['overlap_duration']
            
            cmd = [
                'sox', source_file, str(overlap_path),
                'trim', f'-{overlap_minutes}:00'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                self.logger.info(f"Created overlap buffer: {overlap_minutes} minutes")
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
    
    def _record_segment(self, output_file: str) -> bool:
        """Record a single audio segment with silence detection."""
        try:
            max_duration_seconds = self.config['max_duration'] * 60
            
            arecord_cmd = [
                'arecord',
                '-D', self.config['device'],
                '-f', 'S16_LE',
                '-c', str(self.config['channels']),
                '-r', str(self.config['sample_rate']),
                '-t', 'wav'
            ]
            
            sox_silence_cmd = [
                'sox', '-t', 'wav', '-',
                output_file,
                'silence', '1', '0.1', self.config['silence_threshold'],
                '1', f"{self.config['silence_duration']}", self.config['silence_threshold']
            ]
            
            if self.config['compression_format'] != 'wav':
                sox_silence_cmd.extend(['-C', '0'])
            
            self.logger.info(f"Starting recording: {output_file}")
            
            arecord_proc = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE)
            sox_proc = subprocess.Popen(sox_silence_cmd, stdin=arecord_proc.stdout, 
                                      stderr=subprocess.PIPE)
            arecord_proc.stdout.close()
            
            self.current_process = arecord_proc
            self.recording_active = True
            
            start_time = time.time()
            while self.recording_active and not self.shutdown_requested:
                if arecord_proc.poll() is not None or sox_proc.poll() is not None:
                    break
                    
                if time.time() - start_time > max_duration_seconds:
                    self.logger.info("Maximum duration reached, stopping recording")
                    break
                    
                time.sleep(1)
            
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
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                duration = time.time() - start_time
                self.logger.info(f"Recording completed: {output_file} ({duration:.1f}s)")
                return True
            else:
                self.logger.warning(f"Recording file is empty or too small: {output_file}")
                if os.path.exists(output_file):
                    os.remove(output_file)
                return False
                
        except Exception as e:
            self.logger.error(f"Error during recording: {e}")
            self.recording_active = False
            self.current_process = None
            return False
    
    def _merge_with_overlap(self, overlap_file: str, new_file: str) -> str:
        """Merge overlap buffer with new recording."""
        try:
            file_ext = self.config['compression_format']
            merged_file = new_file.replace(f'.{file_ext}', f'_merged.{file_ext}')
            
            cmd = ['sox', overlap_file, new_file, merged_file]
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
    
    def _signal_handler(self, signum, frame):
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
    
    def run(self):
        """Main recording loop."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("Starting continuous audio recording service")
        self.logger.info(f"Device: {self.config['device']}, Storage: {self.config['storage_path']}")
        
        last_recording_file = None
        
        while not self.shutdown_requested:
            try:
                output_file = self._generate_filename()
                
                if self._record_segment(output_file):
                    if last_recording_file and self.overlap_buffer_path:
                        output_file = self._merge_with_overlap(self.overlap_buffer_path, output_file)
                    
                    if self.overlap_buffer_path:
                        try:
                            os.remove(self.overlap_buffer_path)
                        except OSError:
                            pass
                    
                    self.overlap_buffer_path = self._create_overlap_buffer(output_file)
                    last_recording_file = output_file
                else:
                    self.logger.warning("Recording failed, retrying in 10 seconds")
                    time.sleep(10)
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(10)
        
        if self.overlap_buffer_path and os.path.exists(self.overlap_buffer_path):
            try:
                os.remove(self.overlap_buffer_path)
            except OSError:
                pass
        
        self.logger.info("Audio recording service stopped")


def main():
    parser = argparse.ArgumentParser(description='Raspberry Pi Audio Recorder Service')
    parser.add_argument('--config', '-c', default='config.yaml',
                       help='Path to configuration file (default: config.yaml)')
    parser.add_argument('--validate', action='store_true',
                       help='Validate configuration and dependencies, then exit')
    
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


if __name__ == '__main__':
    sys.exit(main())