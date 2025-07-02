# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based audio recording service for Raspberry Pi that captures continuous audio from ALSA devices with silence-based segmentation. The service runs as a systemd daemon and stores recordings in `/mnt/shared/raspi-audio`.

## Key Architecture Components

- **Main Application**: `raspi_audio_recorder.py` - Core recording service with continuous audio capture
- **Configuration**: Config file (`.ini` or `.yaml`) for device settings, durations, and paths
- **System Integration**: systemd service unit for daemon operation
- **External Dependencies**: SoX for silence detection and audio processing, ALSA for audio capture

## Core Functionality

- **Continuous Recording**: Capture from specified ALSA device without interruption
- **Silence-Based Segmentation**: Split recordings at silence boundaries to avoid cutting speech
- **Overlap Handling**: 5-minute overlap between segments to prevent conversation loss
- **File Management**: UTC timestamp naming (`audio_YYYYMMDD_HHMMSS.wav`) with collision handling (`_vN`)

## Development Requirements

- **Target Platform**: Raspberry Pi 4B with Python 3.7+
- **External Tools**: SoX (subprocess calls), ALSA audio stack
- **Storage**: `/mnt/shared/raspi-audio` directory with write permissions
- **Signal Handling**: Graceful shutdown on SIGINT/SIGTERM
- **Error Recovery**: Retry logic for transient failures, comprehensive logging

## Configuration Parameters

- Audio device name (ALSA)
- Maximum segment duration (default ~60 minutes)
- Overlap duration (default 5 minutes)
- Storage directory path
- Silence detection sensitivity

## Testing and Validation

- Validate audio device availability at startup
- Check storage path existence and write permissions
- Verify SoX dependency availability
- Test signal handling and graceful shutdown
- Validate file naming and collision handling

## Systemd Integration

- Auto-start on boot
- Restart on failure
- System journal logging
- Resource management for long-running operation