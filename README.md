# Raspberry Pi Audio Recorder

A Python-based continuous audio recording service for Raspberry Pi with silence-based segmentation and robust error handling.

## Features

- Continuous audio recording from ALSA devices
- Automatic silence-based segmentation
- Overlap handling between segments to prevent conversation loss
- UTC timestamp file naming with collision handling
- Systemd daemon integration with auto-restart
- Comprehensive error handling and logging
- Configurable audio settings and storage paths

## Requirements

### System Dependencies
- Python 3.7+
- SoX audio processing toolkit
- ALSA audio system
- systemd (for service management)

### Installation Commands
```bash
# Ubuntu/Debian/Raspberry Pi OS
sudo apt update
sudo apt install python3 sox alsa-utils

# Verify installations
sox --version
arecord --list-devices
```

## Installation

1. **Create installation directory:**
   ```bash
   sudo mkdir -p /opt/raspi-audio-recorder
   sudo chown pi:pi /opt/raspi-audio-recorder
   ```

2. **Copy application files:**
   ```bash
   cp raspi_audio_recorder.py /opt/raspi-audio-recorder/
   cp config.ini /opt/raspi-audio-recorder/
   chmod +x /opt/raspi-audio-recorder/raspi_audio_recorder.py
   ```

3. **Create storage directory:**
   ```bash
   sudo mkdir -p /mnt/shared/raspi-audio
   sudo chown pi:audio /mnt/shared/raspi-audio
   sudo chmod 775 /mnt/shared/raspi-audio
   ```

4. **Install systemd service:**
   ```bash
   sudo cp raspi-audio-recorder.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable raspi-audio-recorder.service
   ```

## Configuration

Edit `/opt/raspi-audio-recorder/config.ini` to customize settings:

```yaml
[audio]
device = default                    # ALSA device name
sample_rate = 44100                # Audio sample rate
channels = 1                       # Mono (1) or stereo (2)
silence_threshold = 1%             # Silence detection sensitivity
silence_duration_seconds = 2.0     # Silence duration to trigger split

[recording]
max_duration_minutes = 60          # Maximum segment duration
overlap_minutes = 5                # Overlap between segments

[storage]
directory = /mnt/shared/raspi-audio # Storage directory

[logging]
level = INFO                       # Log level
```

### Audio Device Configuration

List available audio devices:
```bash
arecord -l
```

Test audio recording:
```bash
arecord -D default -f S16_LE -c 1 -r 44100 -t wav test.wav
# Press Ctrl+C to stop, then play with:
aplay test.wav
```

## Usage

### Manual Operation
```bash
# Validate configuration
cd /opt/raspi-audio-recorder
python3 raspi_audio_recorder.py --validate

# Run interactively
python3 raspi_audio_recorder.py --config config.ini
```

### Service Management
```bash
# Start service
sudo systemctl start raspi-audio-recorder

# Check status
sudo systemctl status raspi-audio-recorder

# View logs
sudo journalctl -u raspi-audio-recorder -f

# Stop service
sudo systemctl stop raspi-audio-recorder

# Restart service
sudo systemctl restart raspi-audio-recorder
```

## File Output

Recordings are saved as WAV files with UTC timestamps:
- Format: `audio_YYYYMMDD_HHMMSS.wav`
- Collision handling: `audio_YYYYMMDD_HHMMSS_vN.wav`
- Location: Configured storage directory (default: `/mnt/shared/raspi-audio`)

## Troubleshooting

### Common Issues

1. **Permission denied errors:**
   ```bash
   sudo usermod -a -G audio pi
   sudo chown pi:audio /mnt/shared/raspi-audio
   ```

2. **Audio device not found:**
   ```bash
   # List devices
   arecord -l

   # Test specific device
   arecord -D hw:1,0 -f S16_LE -c 1 -r 44100 -t wav test.wav
   ```

3. **SoX not working:**
   ```bash
   # Reinstall SoX
   sudo apt remove sox
   sudo apt install sox libsox-fmt-all
   ```

4. **Service won't start:**
   ```bash
   # Check service logs
   sudo journalctl -u raspi-audio-recorder -n 50

   # Test manually
   cd /opt/raspi-audio-recorder
   python3 raspi_audio_recorder.py --validate
   ```

### Log Analysis

View real-time logs:
```bash
sudo journalctl -u raspi-audio-recorder -f
```

View recent logs:
```bash
sudo journalctl -u raspi-audio-recorder -n 100
```

Search for errors:
```bash
sudo journalctl -u raspi-audio-recorder | grep ERROR
```

## Monitoring

The service automatically:
- Restarts on failure (up to 3 times per minute)
- Logs all significant events to systemd journal
- Validates dependencies and storage on startup
- Handles SIGTERM/SIGINT gracefully

For production monitoring, consider:
- Disk space alerts for storage directory
- Service status monitoring
- Audio quality validation
- Network connectivity (if using network storage)

## Security Notes

- Service runs with minimal privileges
- Uses `PrivateTmp` and `ProtectSystem` for isolation
- Only writes to configured storage directory
- No network access required for basic operation