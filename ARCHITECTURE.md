# Raspberry Pi Audio Recorder - Architecture Overview

## High-Level Design

The `raspi_audio_recorder.py` service implements a continuous audio recording system with intelligent silence-based segmentation. It runs as a systemd daemon and processes audio in real-time to create discrete recording files separated by silence periods.

## Audio Capture Pipeline

### Recording Process Flow

The audio capture uses a two-process pipeline:

```
ALSA (arecord) → Raw PCM → Python Analysis → SoX Writer → Compressed File
```

1. **arecord** (`raspi_audio_recorder.py:236-248`)
   - Captures raw audio from ALSA device (production: `plughw:1,0` - USB microphone)
   - Format: S16_LE (signed 16-bit little-endian PCM)
   - Configurable sample rate (default: 44100 Hz, **production: 16000 Hz**)
   - Channels: mono (1 channel)
   - Outputs to stdout as raw PCM stream

2. **Python Middleware** (`raspi_audio_recorder.py:292-358`)
   - Reads raw PCM data in 1-second chunks
   - Calculates RMS (Root Mean Square) audio levels for silence detection
   - Forwards data to SoX for writing
   - Implements dual-phase detection (leading silence skip + trailing silence detection)

3. **SoX Writer** (`raspi_audio_recorder.py:250-268`)
   - Receives raw PCM from Python via stdin
   - Encodes to final format (WAV by default, **production: FLAC compressed**)
   - Writes to temporary directory (`.tmp/`)
   - Compression saves ~50% disk space vs uncompressed WAV

## Silence Detection System

### Two-Phase Detection Model

The service implements sophisticated silence detection with two distinct phases:

#### Phase 1: Leading Silence Skip (Sound Detection)

**Purpose**: Wait for actual sound before starting the recording timer

**Location**: `raspi_audio_recorder.py:322-328`

**Behavior**:
- Continuously monitors audio chunks before recording starts
- Calculates RMS level for each 1-second chunk
- When RMS ≥ silence threshold (e.g., 1%): sound detected
- Resets the recording timer at first sound
- Prevents recording long periods of silence at the beginning

**Example**:
```
[silence] [silence] [SOUND!] ← Timer starts here
                     ↑
              Recording begins
```

#### Phase 2: Trailing Silence Detection (Recording Stop)

**Purpose**: Stop recording after sustained silence, but only after minimum duration

**Location**: `raspi_audio_recorder.py:333-354`

**Behavior**:
- Only activates after `min_duration` seconds (default: 45s)
- Tracks continuous silence duration
- Stops recording when silence ≥ `silence_duration` seconds (default: 2s)
- Resets silence timer if sound resumes
- Ensures recordings capture complete conversations

**Example**:
```
[sound] [sound] [silence 1s] [silence 2s] ← Stop recording
                              ↑
                      Silence threshold met
```

### RMS Calculation

**Method**: `_calculate_rms()` (`raspi_audio_recorder.py:200-220`)

**Algorithm**:
```python
RMS = sqrt(sum(sample²) / sample_count)
Normalized_RMS = (RMS / 32768) × 100%
```

- Unpacks S16_LE samples (range: -32768 to +32767)
- Computes root mean square of sample values
- Normalizes to 0-100% scale for threshold comparison
- Processes 1-second chunks:
  - Production (16 kHz): 16,000 samples/second
  - Default (44.1 kHz): 44,100 samples/second

### Configuration Parameters

| Parameter | Config Key | Default | Current Production | Purpose |
|-----------|-----------|---------|-------------------|---------|
| Silence Threshold | `silence_threshold` | 1% | **5%** | RMS level below which audio is "silent" |
| Silence Duration | `silence_duration_seconds` | 2.0s | **15.0s** | How long silence must persist to stop |
| Minimum Duration | `min_duration_seconds` | 45s | **45s** | Minimum recording length before checking silence |

**Note**: Production config uses higher thresholds to handle noisier office environments and longer pauses in conversations.

## File Management System

### Three-Stage File Lifecycle

```
1. Temporary File (.tmp/) → 2. Overlap Buffer (.tmp/.overlap_buffer) → 3. Final File (/mnt/shared/raspi-audio/)
```

#### Stage 1: Temporary Recording

**Location**: `raspi_audio_recorder.py:141-165`

**Process**:
1. Generate filename: `{prefix}_{YYYYMMDD_HHMMSS}_{samplerate}kHz.{ext}`
   - Example (production): `krusty_office_20250113_143022_16kHz.flac`
   - Default example: `audio_20250113_143022_44kHz.wav`
2. Create paths:
   - Temp (production): `/hddzfs/raspi-audio/.tmp/krusty_office_20250113_143022_16kHz.flac`
   - Final (production): `/hddzfs/raspi-audio/krusty_office_20250113_143022_16kHz.flac`
   - Default: `/mnt/shared/raspi-audio/` paths
3. Check for collisions, append `_vN` suffix if needed
4. Record to temp directory during capture

**Collision Handling**:
```
krusty_office_20250113_143022_16kHz.flac       (original)
krusty_office_20250113_143022_16kHz_v1.flac    (if collision)
krusty_office_20250113_143022_16kHz_v2.flac    (if another collision)
```

#### Stage 2: Overlap Merging

**Location**: `raspi_audio_recorder.py:167-198, 408-427`

**Purpose**: Prevent losing audio at segment boundaries

**Process**:
1. After successful recording, extract last N minutes using SoX:
   ```bash
   # Production: 2 minutes overlap
   sox {previous_file} .overlap_buffer.flac trim -2:00

   # Default: 5 minutes overlap
   sox {previous_file} .overlap_buffer.wav trim -5:00
   ```
2. Store as `.tmp/.overlap_buffer.{ext}`
3. On next recording, prepend overlap to new file:
   ```bash
   sox {overlap_buffer} {new_recording} {merged_output}
   ```
4. Replace new recording with merged version
5. Delete old overlap buffer

**Timeline Example (Production: 2-minute overlap)**:
```
Recording 1: [============================] (120 min max)
                                    [==] ← Extract 2 min overlap

Recording 2:                   [==][============================] (122 min total)
                               ↑  ↑
                          Overlap New audio
```

#### Stage 3: Final Storage

**Location**: `raspi_audio_recorder.py:429-439`

**Process**:
1. Move from `.tmp/` to final storage directory
2. Use `shutil.move()` for atomic operation
3. Update tracking set (`current_temp_files`)
4. Log final location

**Cleanup on Shutdown** (`raspi_audio_recorder.py:441-450`):
- Remove all files in `current_temp_files` set
- Includes incomplete recordings and overlap buffers
- Prevents orphaned temporary files

### File Validation

**Post-Recording Checks** (`raspi_audio_recorder.py:377-400`):

1. **File Existence**: Check file was created
2. **Minimum Size**: Reject files < 1000 bytes (likely corrupt)
3. **Minimum Duration**: Reject recordings < `min_duration` seconds
   - Short recordings are deleted and not saved
   - Service continues to next segment immediately

## Duration Controls

### Three Duration Limits

| Type | Config Key | Default | Production | Purpose | Enforcement |
|------|-----------|---------|-----------|---------|-------------|
| **Minimum** | `min_duration_seconds` | 45s | **45s** | Filter out brief noises | Post-recording validation |
| **Maximum** | `max_duration_minutes` | 60 min | **120 min** | Prevent runaway files | Emergency stop during recording |
| **Overlap** | `overlap_minutes` | 5 min | **2 min** | Continuity between segments | Applied during merge |

### Recording Lifecycle Timeline

**Production Configuration**:
```
T=0s    : Sound detected, timer starts
T=45s   : Minimum duration reached, silence detection activates
T=?     : Silence detected for 15s → Stop recording
T=7200s : Maximum duration (120 min) → Emergency stop (if no silence)
```

**Default Configuration**:
```
T=0s    : Sound detected, timer starts
T=45s   : Minimum duration reached, silence detection activates
T=?     : Silence detected for 2s → Stop recording
T=3600s : Maximum duration (60 min) → Emergency stop (if no silence)
```

## Configuration System

### Config File Format (`raspi_audio_recorder.py:38-76`)

Supports INI format with sections:

**Production Configuration** (`config.ini`):
```ini
[audio]
device = plughw:1,0
sample_rate = 16000
channels = 1
silence_threshold = 5%
silence_duration_seconds = 15.0
compression_format = flac

[recording]
max_duration_minutes = 120
overlap_minutes = 2
min_duration_seconds = 45

[storage]
directory = /hddzfs/raspi-audio
filename_prefix = krusty_office

[logging]
level = DEBUG
```

**Default Example Configuration**:
```ini
[audio]
device = default
sample_rate = 44100
channels = 1
silence_threshold = 1%
silence_duration_seconds = 2.0
compression_format = wav

[recording]
max_duration_minutes = 60
overlap_minutes = 5
min_duration_seconds = 45

[storage]
directory = /mnt/shared/raspi-audio
filename_prefix = audio

[logging]
level = INFO
```

**Key Production Differences**:
- **16 kHz sample rate**: Lower rate suitable for voice recording, reduces file size by ~64%
- **5% silence threshold**: Higher threshold compensates for office background noise
- **15 second silence duration**: Longer pauses allowed (natural conversation breaks)
- **FLAC compression**: Lossless compression saving ~50% disk space
- **120 minute max duration**: Extended for long meetings/conversations
- **2 minute overlap**: Shorter overlap reduces redundancy while maintaining continuity

### Validation on Startup

**Dependencies** (`raspi_audio_recorder.py:91-116`):
- SoX: Version check via `sox --version`
- ALSA: Device check via `arecord --list-devices`
- Raises `RuntimeError` if not available

**Storage** (`raspi_audio_recorder.py:118-139`):
- Create storage directory if missing
- Create `.tmp/` subdirectory
- Test write permissions with `.write_test` file
- Raises `RuntimeError` if not writable

## Signal Handling and Shutdown

### Graceful Shutdown Process (`raspi_audio_recorder.py:452-465`)

**Signals Handled**: SIGINT (Ctrl+C), SIGTERM (systemd stop)

**Shutdown Sequence**:
1. Set `shutdown_requested = True` flag
2. Set `recording_active = False` to stop main loop
3. Terminate `arecord` subprocess
4. Wait up to 5 seconds for clean exit
5. Force kill if timeout exceeded
6. Call `_cleanup_temp_files()` to remove incomplete recordings
7. Exit gracefully

**Main Loop Respects Flags** (`raspi_audio_recorder.py:479-524`):
- Checks `shutdown_requested` before each recording
- Breaks loop on exception or signal
- Ensures final cleanup always runs

## Error Handling Strategy

### Retry and Continue Philosophy

The service prioritizes continuous operation over individual recording failures:

**Transient Failures** (`raspi_audio_recorder.py:504-508`):
- Too-short recordings: Delete and continue immediately
- Failed recordings: Sleep 1 second, retry
- Empty files: Remove and continue

**Fatal Failures** (`raspi_audio_recorder.py:512-514`):
- Unexpected exceptions: Log error, sleep 10 seconds, retry
- Missing dependencies: Fail at startup (fail-fast)
- Storage issues: Fail at startup (fail-fast)

### Logging Strategy (`raspi_audio_recorder.py:78-89`)

**Output**: stdout (captured by systemd journal)

**Log Levels**:
- **INFO**: Normal operation (start, stop, file creation, sound detection)
- **WARNING**: Recoverable issues (overlap merge failure, short recordings)
- **ERROR**: Serious problems (subprocess crashes, I/O errors)
- **DEBUG**: Detailed silence detection events (commented in code)

## Main Loop Architecture

### Continuous Recording Cycle (`raspi_audio_recorder.py:467-524`)

```
┌─────────────────────────────────┐
│  Initialize service             │
│  Set up signal handlers         │
└────────────┬────────────────────┘
             │
             ↓
┌─────────────────────────────────┐
│  While not shutdown_requested:  │◄─────┐
│  1. Generate filename           │      │
│  2. Record segment              │      │
│  3. Check if valid              │      │
│  4. Merge with overlap          │      │
│  5. Move to final location      │      │
│  6. Create new overlap buffer   │      │
└────────────┬────────────────────┘      │
             │                           │
             └───────────────────────────┘
             │
             ↓
┌─────────────────────────────────┐
│  Cleanup temp files             │
│  Log shutdown                   │
└─────────────────────────────────┘
```

### State Machine

**States**:
- `recording_active`: Currently capturing audio
- `shutdown_requested`: Signal received, finishing up
- `sound_detected`: Passed leading silence phase
- `silence_start_time`: Tracking trailing silence

**State Transitions**:
```
IDLE → WAITING_FOR_SOUND → RECORDING → CHECKING_SILENCE → STOPPING → IDLE
```

## Performance Characteristics

### Resource Usage

**CPU**:
- RMS calculation: O(n) per second of audio (n = sample_rate × channels)
- Production overhead: ~16,000 operations/second for 16kHz mono
- Default overhead: ~44,100 operations/second for 44.1kHz mono
- SoX subprocess handles compression
- Very low CPU usage on Raspberry Pi 4B (<5% typical)

**Memory**:
- Chunk size calculation: `sample_rate × channels × 2 bytes`
- Production: 32,000 bytes/second (16 kHz × 1 × 2)
- Default: 88,200 bytes/second (44.1 kHz × 1 × 2)
- No large buffers accumulated in Python
- Streaming architecture prevents memory growth
- Typical RSS: <50 MB

**Disk I/O**:
- Sequential writes to temp directory
- Production (16kHz FLAC): ~1-2 MB/minute
- Default (44.1kHz WAV): ~10 MB/minute
- Atomic moves from temp to final (no copy overhead)
- Disk usage comparison (120-minute recording):
  - Production: ~120-240 MB per recording
  - Default: ~1.2 GB per recording

### Latency

**Recording Start**: ~1-2 seconds after sound detection
- Real-time RMS analysis
- No buffering delay

**Recording Stop**:
- Production: 15-16 seconds after silence begins
- Default: 2-3 seconds after silence begins
- Configurable silence duration
- Grace period prevents false stops during natural conversation pauses

## Integration Points

### Systemd Service

**Expected Service Unit**:
```ini
[Unit]
Description=Raspberry Pi Audio Recorder
After=sound.target network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/raspi_audio_recorder.py --config /path/to/config.ini
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

**Logging**: All output goes to stdout → systemd journal
- View logs: `journalctl -u raspi-audio-recorder -f`

### External Dependencies

**Runtime Requirements**:
- Python 3.7+ (uses type hints, f-strings)
- SoX: Audio format conversion and file operations
- ALSA: Audio device access (arecord)
- systemd: Service management (optional but recommended)

**Python Modules** (standard library only):
- `subprocess`: External process management
- `struct`: Binary PCM data parsing
- `signal`: Graceful shutdown
- `configparser`: Config file parsing
- `pathlib`: File path operations

## Production Deployment Context

### "Krusty Office" Configuration

The production deployment runs in an office environment with the following characteristics:

**Environment**:
- Location: Office space with ambient background noise
- Audio source: Conversations, meetings, phone calls
- Recording device: USB microphone (`plughw:1,0`)
- Storage: ZFS pool at `/hddzfs/raspi-audio`

**Configuration Rationale**:

1. **16 kHz Sample Rate**
   - Voice-optimized frequency range (human speech: 300-3400 Hz)
   - Reduces file size by 64% vs 44.1 kHz
   - Sufficient quality for speech recognition and transcription
   - Lower CPU/memory requirements

2. **5% Silence Threshold**
   - Office environments have higher ambient noise (HVAC, computers, keyboards)
   - 1% threshold would trigger on background noise
   - Prevents premature recording stops
   - Tested empirically for the specific environment

3. **15 Second Silence Duration**
   - Natural conversation pauses can be 5-10 seconds
   - Prevents splitting single conversations into multiple files
   - Allows for thinking time, reading, phone dialing
   - Reduces fragmentation of meeting recordings

4. **120 Minute Maximum Duration**
   - Accommodates long meetings/conference calls
   - Average meeting duration: 30-90 minutes
   - 2-hour safety cap prevents infinite recordings
   - Still manageable file sizes (~240 MB with FLAC)

5. **2 Minute Overlap**
   - Shorter than default (5 min) to reduce redundancy
   - Sufficient to capture context at segment boundaries
   - Saves disk space while maintaining continuity
   - Testing showed 2 minutes adequate for conversation context

6. **FLAC Compression**
   - Lossless compression preserves full quality
   - ~50% space savings vs WAV
   - Fast decompression for playback/transcription
   - Industry-standard format with broad compatibility

## Troubleshooting Guide

### Common Issues

**No Audio Captured**:
- Check ALSA device name in config: `arecord -l`
- Verify microphone permissions
- Test with: `arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 test.wav`
- Check USB microphone connection: `lsusb`

**Files Too Short** (recordings stop too early):
- Lower `min_duration_seconds` (but keep > 30s to filter noise)
- **Increase** `silence_threshold` (e.g., 1% → 3% → 5%)
  - Higher = less sensitive, requires louder sound to detect
  - More audio will be considered "silence", leading to longer recordings
- Increase `silence_duration_seconds` (e.g., 2s → 5s → 10s)
  - Longer pauses allowed before stopping
- Check microphone levels: `alsamixer`
- Monitor RMS levels in DEBUG logs

**Recording Never Stops** (files hit max duration):
- **Decrease** `silence_threshold` (e.g., 5% → 3% → 1%)
  - Lower = more sensitive, detects quieter silence
  - More audio will be considered "sound", requiring actual silence to stop
- Decrease `silence_duration_seconds` (e.g., 15s → 10s → 5s)
  - Shorter silence needed to stop
- Check for background noise sources (fans, HVAC)
- View live audio levels: `arecord -D <device> -f S16_LE -r 16000 -c 1 -V mono /dev/null`

**Silence Threshold Adjustment Guide**:
```
Background Noise Level:
  Low (quiet room)     → Use 1-2% threshold
  Medium (office)      → Use 3-5% threshold
  High (loud room)     → Use 6-10% threshold

Problem: Stops too early → INCREASE threshold
Problem: Never stops    → DECREASE threshold
```

**Storage Full**:
- Monitor disk usage: `df -h /hddzfs/raspi-audio`
- Implement external cleanup script for old recordings:
  ```bash
  # Delete recordings older than 30 days
  find /hddzfs/raspi-audio -name "*.flac" -mtime +30 -delete
  ```
- Adjust `max_duration_minutes` to create smaller files
- Consider lower sample rate (16000 → 8000 for phone-quality)
- Verify FLAC compression is enabled (not WAV)

**Service Won't Start**:
- Check systemd status: `systemctl status raspi-audio-recorder`
- View logs: `journalctl -u raspi-audio-recorder -n 50`
- Validate config: `python3 raspi_audio_recorder.py --config config.ini --validate`
- Check storage path permissions: `ls -ld /hddzfs/raspi-audio`
- Verify SoX installed: `sox --version`

## Future Enhancement Areas

### Potential Improvements

1. **Dynamic Threshold Adjustment**: Auto-calibrate silence threshold based on ambient noise
2. **Compression Format Support**: Add FLAC, Opus, MP3 output options (already partially supported)
3. **Remote Monitoring**: REST API or WebSocket for status monitoring
4. **Disk Space Management**: Automatic cleanup of old recordings when space low
5. **Audio Quality Metrics**: Track and log SNR, clipping, recording quality
6. **Multiple Device Support**: Concurrent recording from multiple microphones
7. **Cloud Upload**: Automatic sync to cloud storage (S3, Google Drive, etc.)

## Security Considerations

### Current Implementation

**File Permissions**:
- Inherits from parent directory
- No explicit permission setting
- Recommend: Set storage directory to 0700 (owner only)

**Process Isolation**:
- Runs as systemd service user
- No privilege escalation
- No network exposure

**Input Validation**:
- Config file: Basic type checking via configparser
- File paths: No sanitization (trusts config file)
- Audio data: No validation (trusts hardware/driver)

### Recommendations

1. Run as dedicated non-root user
2. Set restrictive permissions on storage directory
3. Consider AppArmor/SELinux profile for systemd service
4. Validate config file paths to prevent directory traversal
5. Implement disk quota limits for storage directory
