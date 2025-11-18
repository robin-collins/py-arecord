# VAD Data Collection and Analysis Guide

This guide explains how to use the VAD data collection and analysis tools to optimize your Voice Activity Detection configuration.

## Overview

The VAD tuning system consists of two companion applications:

1. **`vad_data_collector.py`** - Collects real-time audio metrics and user-tagged metadata
2. **`vad_analyzer.py`** - Analyzes collected data and recommends optimal configuration values

## Installation

### Dependencies

```bash
# Install Python dependencies
pip3 install -r requirements_collector.txt

# Verify webrtcvad is installed (required for VAD)
python3 -c "import webrtcvad; print('WebRTC VAD available')"

# Verify matplotlib for visualizations (optional)
python3 -c "import matplotlib; print('Matplotlib available')"
```

### Configuration

Edit `vad_collector_config.ini` to match your audio setup:

```ini
[audio]
# Should match your main recorder device
device = plughw:1,0
sample_rate = 16000
channels = 1

[vad]
# Copy settings from config.ini for consistency
use_vad = true
vad_aggressiveness = 1
vad_frame_duration_ms = 10
noise_floor_threshold = 4.0
silence_threshold = 5.0

[database]
# Where to store collected data
db_path = /mnt/shared/raspi-audio/vad_data.db
retention_days = 30
```

## Usage Workflow

### Step 1: Collect Data

Start the data collector in a terminal:

```bash
python3 vad_data_collector.py --config vad_collector_config.ini
```

You'll see a live status display:

```
🔊 SPEECH | RMS: 12.34% | FPS: 100.0 | Tags: 1 Speaker Close [23s]
```

### Step 2: Tag Audio Conditions

While the collector is running, press hotkeys to tag audio conditions:

**Timed Tags (30 seconds):**
- `[1]` - One speaker close to mic
- `[2]` - Two speakers speaking, variable distance
- `[0]` - Music playing
- `[9]` - Video playing
- `[8]` - Loud ambient noise

**Persistent Tags (toggle on/off):**
- `[q]` - One speaker close to mic (persistent)
- `[w]` - Two speakers speaking (persistent)
- `[p]` - Music playing (persistent)
- `[o]` - Video playing (persistent)
- `[i]` - Loud ambient noise (persistent)

**Other Keys:**
- `[h]` - Show hotkey help
- `[Ctrl+C]` - Stop collector

**Example Tagging Workflow:**

1. Have someone speak close to the microphone → Press `[1]`
2. Play music for a few minutes → Press `[p]` to start, `[p]` again to stop
3. Have a two-person conversation → Press `[q]` at start, `[q]` when done
4. Capture various ambient noise levels

**Best Practices:**
- Collect at least 30-60 minutes of data across different conditions
- Tag generously - more tagged data = better recommendations
- Include edge cases (whispers, distant speech, background TV, etc.)
- Leave collector running during normal daily activities

### Step 3: Analyze Statistics

View overall statistics:

```bash
python3 vad_analyzer.py --db /mnt/shared/raspi-audio/vad_data.db stats
```

Output:
```
======================================================================
VAD DATA STATISTICS
======================================================================

Time Range:
  Start:    2025-01-15T10:30:00
  End:      2025-01-15T11:45:00
  Duration: 1.25 hours

Audio Metrics:
  Total frames: 450,000
  Speech frames: 125,000 (27.78%)
  Silence frames: 325,000

RMS Level Statistics:
  Average: 6.23%
  Minimum: 0.12%
  Maximum: 45.67%

Metadata Events:
  Total events: 23
  Unique tags: 5

  Tag Distribution:
    one_speaker_close              :    12
    two_speakers                   :     5
    music_playing                  :     4
    loud_ambient                   :     2
```

### Step 4: Generate Recommendations

Analyze data and get configuration suggestions:

```bash
python3 vad_analyzer.py --db /mnt/shared/raspi-audio/vad_data.db recommend
```

Output:
```
======================================================================
VAD CONFIGURATION RECOMMENDATIONS
======================================================================

noise_floor_threshold:
  Recommended: 3.8
  Confidence: high
  Reason: 90th percentile of silence RMS levels
  Analysis:
    silence_rms_median: 1.23
    silence_rms_p75: 2.45
    silence_rms_p90: 3.78
    silence_rms_p95: 4.12

silence_threshold:
  Recommended: 5.2
  Confidence: high
  Reason: Clear separation between speech and silence RMS distributions
  Analysis:
    silence_p95: 4.12
    speech_p5: 6.34
    separation: 2.22

vad_aggressiveness:
  Recommended: 2
  Confidence: medium
  Reason: Moderate false positive rate, balanced aggressiveness recommended
  Analysis:
    music_false_positive_rate: 18.45
    ambient_false_positive_rate: 12.33

silence_duration_seconds:
  Recommended: 12.5
  Confidence: high
  Reason: 95th percentile of natural pause durations during speech
  Analysis:
    pause_p75: 8.2
    pause_p90: 10.5
    pause_p95: 12.5

======================================================================
SUGGESTED CONFIG.INI CHANGES:
======================================================================

[audio]
noise_floor_threshold = 3.8
silence_threshold = 5.2
vad_aggressiveness = 2
silence_duration_seconds = 12.5
```

### Step 5: Apply Recommendations

Update `config.ini` with the recommended values:

```ini
[audio]
noise_floor_threshold = 3.8
silence_threshold = 5.2
vad_aggressiveness = 2
silence_duration_seconds = 12.5
```

Restart the main audio recorder to apply changes:

```bash
sudo systemctl restart raspi-audio-recorder
```

### Step 6: Validate and Iterate

1. Monitor the main recorder for a few days
2. Check if recordings are capturing speech appropriately
3. Collect more data in specific problem scenarios
4. Re-run analysis and fine-tune as needed

## Advanced Usage

### Query and Export Data

Export metrics to CSV for external analysis:

```bash
# Export last hour of data
python3 vad_analyzer.py query --start -1h --output last_hour.csv

# Export specific time range
python3 vad_analyzer.py query \
  --start 2025-01-15T10:00:00 \
  --end 2025-01-15T12:00:00 \
  --output morning_session.csv

# Export only music-tagged data
python3 vad_analyzer.py query --tags music_playing --output music_analysis.csv
```

### Visualize Data

Generate charts of RMS levels and speech detection:

```bash
# Visualize last 30 minutes
python3 vad_analyzer.py visualize --start -30m --output visualization.png

# Show interactive plot
python3 vad_analyzer.py visualize --start -1h --show
```

### Data Cleanup

Remove old data to free space:

```bash
# Delete data older than 30 days (with confirmation)
python3 vad_analyzer.py cleanup --older-than 30

# Delete without confirmation prompt
python3 vad_analyzer.py cleanup --older-than 30 --yes
```

## Troubleshooting

### Collector Not Starting

**Error: "Failed to start arecord"**
- Check audio device name: `arecord -L`
- Verify device in `vad_collector_config.ini`
- Ensure main recorder isn't using the device

**Error: "webrtcvad module not available"**
- Install: `pip3 install webrtcvad`
- Collector falls back to RMS-only detection

### No Recommendations Generated

**"Insufficient data"**
- Collect at least 15-30 minutes of tagged data
- Ensure variety of speech and silence conditions
- Add more metadata tags during collection

**"No tagged speech data"**
- Use hotkeys to tag speech periods (press `[1]` or `[q]` during speech)
- Tags are essential for accurate recommendations

### High Database Size

Check database size:
```bash
ls -lh /mnt/shared/raspi-audio/vad_data.db
```

Reduce size:
- Set `store_audio_chunks = false` in config (only stores metrics, not raw audio)
- Lower `retention_days` value
- Run cleanup regularly: `vad_analyzer.py cleanup --older-than 7`

## Understanding Recommendations

### noise_floor_threshold
- **Purpose**: Skip VAD processing for absolute silence
- **Impact**: Higher = more aggressive filtering, lower CPU usage
- **Typical Range**: 2-5%
- **Too High**: Might miss quiet speech
- **Too Low**: Wastes CPU on obvious silence

### silence_threshold
- **Purpose**: RMS-only fallback threshold (when VAD disabled)
- **Impact**: Determines speech vs. silence in RMS-only mode
- **Typical Range**: 3-8%
- **Too High**: Misses quiet speech
- **Too Low**: False positives on background noise

### vad_aggressiveness
- **Purpose**: WebRTC VAD filtering strictness
- **Levels**:
  - `0` = Very lenient (captures most sounds)
  - `1` = Balanced (good for clear speech)
  - `2` = Aggressive (filters non-speech better)
  - `3` = Very aggressive (strictest filtering)
- **Too High**: Might miss soft-spoken speech
- **Too Low**: False positives on music, TV, typing

### silence_duration_seconds
- **Purpose**: How long silence must persist before stopping recording
- **Impact**: Balances completeness vs. file size
- **Typical Range**: 10-20 seconds
- **Too High**: Very long recordings with trailing silence
- **Too Low**: Cuts off during natural conversation pauses

## Files and Directories

- `vad_database.py` - SQLite database operations
- `vad_metadata.py` - Metadata state machine and hotkey mapping
- `vad_hotkeys.py` - Terminal keyboard input handler
- `vad_data_collector.py` - Main collector application
- `vad_analyzer.py` - CLI analysis tool
- `vad_recommender.py` - Configuration recommendation engine
- `vad_collector_config.ini` - Collector configuration
- `requirements_collector.txt` - Python dependencies

## Performance Considerations

### Raspberry Pi Resource Usage

**Data Collector:**
- CPU: ~15-25% (with VAD), ~5-10% (RMS-only)
- Memory: ~50-100 MB
- Disk writes: ~1-2 MB/hour (without audio chunks), ~100-200 MB/hour (with chunks)

**Recommendations:**
- Run on same Raspberry Pi as main recorder (minimal overhead)
- Use `store_audio_chunks = false` to save disk space
- Set reasonable `retention_days` to prevent database bloat
- Close collector when not actively tuning

### Database Performance

SQLite optimizations enabled by default:
- WAL mode for better concurrency
- Batch inserts (1-second intervals)
- Indexed queries for fast time-range lookups

## Support and Feedback

For issues or questions:
1. Check the troubleshooting section above
2. Review log file: `/mnt/shared/raspi-audio/vad_collector.log`
3. Examine database stats: `vad_analyzer.py stats`

## Best Practices Summary

1. **Before Collection**: Configure audio device to match main recorder
2. **During Collection**: Tag generously across various audio conditions
3. **Collect Duration**: At least 30-60 minutes for reliable recommendations
4. **Tag Variety**: Include all expected audio scenarios (speech, music, noise)
5. **Analysis Timing**: Run recommendations after substantial tagged data collection
6. **Validation**: Test new config values for several days before finalizing
7. **Iteration**: Re-collect data if environment changes significantly
8. **Cleanup**: Regularly remove old data to maintain performance

## License

Same license as main raspi-audio-recorder project.
