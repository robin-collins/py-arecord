# Raspberry Pi Audio Recorder

A Python-based continuous audio recording service for Raspberry Pi with silence-based segmentation and robust error handling.

## Features

- Continuous audio recording from ALSA devices
- **WebRTC VAD (Voice Activity Detection)** for intelligent speech vs. noise detection
- Two-stage detection: RMS pre-filter + WebRTC VAD for efficient processing
- Python-based real-time audio level monitoring and silence detection
- Configurable minimum recording duration (silence detection disabled until reached)
- Automatic silence-based segmentation after minimum duration
- Filters out door slams, machinery noise, and other non-speech sounds automatically
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
- webrtcvad Python package (optional, for speech detection)

### Installation Commands
```bash
# Ubuntu/Debian/Raspberry Pi OS
sudo apt update
sudo apt install python3 python3-pip sox alsa-utils

# Install Python dependencies
pip3 install -r requirements.txt
# Or manually: pip3 install webrtcvad

# Verify installations
sox --version
arecord --list-devices
python3 -c "import webrtcvad; print('WebRTC VAD installed')"
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
sample_rate = 16000                # Audio sample rate (VAD requires 8000/16000/32000/48000)
channels = 1                       # Mono (1) or stereo (2)

# Voice Activity Detection (Speech detection)
use_vad = true                     # Enable WebRTC VAD (recommended)
vad_aggressiveness = 2             # 0-3: 0=lenient, 2=balanced, 3=very-aggressive
vad_frame_duration_ms = 30         # Frame size: 10, 20, or 30 ms
noise_floor_threshold = 1.0%       # RMS pre-filter before VAD
silence_threshold = 1%             # Fallback threshold if VAD disabled
silence_duration_seconds = 2.0     # Continuous non-speech before stopping

[recording]
max_duration_minutes = 60          # Maximum segment duration
min_duration_seconds = 45          # Minimum recording duration before silence detection activates
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
arecord -D default -f S16_LE -c 1 -r 16000 -t wav test.wav
# Press Ctrl+C to stop, then play with:
aplay test.wav
```

### Voice Activity Detection (VAD) Configuration

The service uses WebRTC VAD to distinguish speech from non-speech sounds:

**Aggressiveness Levels** (`vad_aggressiveness`):
- `0`: **Quality mode** - Lenient, captures all speech-like sounds (more false positives)
- `1`: **Low bitrate mode** - Balanced for low-quality connections
- `2`: **Aggressive mode** (recommended) - Good balance, filters most non-speech
- `3`: **Very aggressive mode** - Strict, may miss quiet speech but excellent noise filtering

**Frame Duration** (`vad_frame_duration_ms`):
- `10ms`: Most responsive, highest CPU usage
- `20ms`: Balanced
- `30ms`: (recommended) Slightly less responsive, lower CPU usage

**Noise Floor Threshold** (`noise_floor_threshold`):
- RMS level below which audio is considered absolute silence
- VAD is skipped for chunks below this level (efficiency optimization)
- Typical range: 0.5% - 2.0%

**Sample Rate Requirements**:
- VAD only works with: 8000, 16000, 32000, or 48000 Hz
- Recommended: **16000 Hz** (optimal for speech, lower file sizes)
- If VAD unavailable or disabled, falls back to RMS-only detection

**Disabling VAD**:
Set `use_vad = false` to use simple RMS-based detection (faster, less accurate)

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

## Recording Behavior

The service uses Python-based real-time audio level monitoring to control when recordings start and stop:

### How It Works

1. **Waits for sound**: Continuously monitors audio levels until sound is detected above the silence threshold
2. **Starts recording**: When sound is detected, recording begins and the timer starts
3. **Ignores silence initially**: For the first `min_duration_seconds` (e.g., 45 seconds), continues recording regardless of silence
4. **Activates silence detection**: After minimum duration is reached, begins monitoring for silence
5. **Stops on silence**: If silence is detected (below threshold for `silence_duration_seconds`), recording stops and file is saved
6. **Continues on speech**: If speech continues beyond minimum duration, recording keeps going until silence is detected
7. **Maximum duration**: If recording reaches `max_duration_minutes`, it stops and starts a new file with overlap

### Example Scenarios

**Scenario A**: Brief speech (15 seconds)
- Sound detected → recording starts
- Speech continues for 15 seconds, then silence
- Recording continues until 45 seconds (minimum duration)
- At 45 seconds, silence is detected → recording stops
- Result: One 45-second recording

**Scenario B**: Extended speech (5 minutes)
- Sound detected → recording starts
- Speech continues for 5 minutes
- At 45 seconds: minimum duration reached, silence detection activates
- At 5 minutes: speech ends, silence detected → recording stops
- Result: One 5-minute recording

**Scenario C**: Very long speech (130 minutes)
- Sound detected → recording starts
- Speech continues past 120 minutes (max duration)
- At 120 minutes: recording stops, new recording starts with 2-minute overlap
- Speech continues for another 10 minutes, then silence detected
- Result: Two recordings (120 minutes and 12 minutes with 2-minute overlap)

## File Output

Recordings are saved with UTC timestamps and sample rate:
- Format: `audio_YYYYMMDD_HHMMSS_NNkHz.{ext}`
- Collision handling: `audio_YYYYMMDD_HHMMSS_NNkHz_vN.{ext}`
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