# File Tree

```
py-arecord/
├── ARCHITECTURE.md                     # Detailed technical architecture documentation
├── CHANGELOG.md                        # Project changelog
├── CLAUDE.md                           # Claude Code guidance
├── CODE_ANALYSIS.md                    # Code review with logic flow analysis and recommendations
├── FILETREE.md                         # This file tree documentation
├── ISSUES.md                           # Prioritized issue tracker with fixes needed
├── README.md                           # Project documentation
├── README_VAD_TUNING.md                # VAD tuning guide with data collection workflow
├── SILENCE_THRESHOLD.md                # Guide for tuning silence detection parameters
├── config.ini                          # Configuration file with audio/recording settings
├── config.ini.example                  # Example configuration file
├── install-raspi-audio-recorder.sh     # Installation script for systemd service
├── py-arecord.md                       # Additional project documentation
├── raspi-audio-recorder.service        # systemd service unit file
├── raspi_audio_recorder.py             # Main application - audio recording service
├── requirements.txt                    # Python dependencies (webrtcvad)
├── requirements_collector.txt          # Dependencies for VAD data collector and analyzer
├── vad_analyzer.py                     # VAD data analyzer CLI tool (query, stats, visualize, recommend)
├── vad_collector_config.ini            # Configuration for VAD data collector
├── vad_data_collector.py               # VAD data collection daemon with hotkey metadata tagging
├── vad_database.py                     # SQLite database operations for VAD metrics storage
├── vad_hotkeys.py                      # Terminal-based hotkey input handler
├── vad_metadata.py                     # Metadata state machine for tag management
└── vad_recommender.py                  # Configuration recommendation engine
```

## Key Files

### Core Application

- **raspi_audio_recorder.py**: Core Python application with WebRTC VAD, continuous audio recording, speech detection, and file management
- **config.ini**: Configuration file with audio device, VAD settings, compression format, sample rate, and recording parameters
- **config.ini.example**: Example configuration with documented settings
- **requirements.txt**: Python dependencies (webrtcvad for speech detection)
- **install-raspi-audio-recorder.sh**: Installation script that deploys the service, configures systemd, and sets up permissions
- **raspi-audio-recorder.service**: systemd service configuration for daemon operation

### VAD Data Collection and Analysis

- **vad_data_collector.py**: Standalone data collection daemon that captures real-time VAD metrics (RMS levels, speech detection) and logs to SQLite database with hotkey-based metadata tagging
- **vad_analyzer.py**: CLI tool for analyzing collected data with commands: query (export CSV), stats (summary statistics), visualize (matplotlib charts), recommend (configuration suggestions), cleanup (retention management)
- **vad_database.py**: SQLite3 database schema and operations with WAL mode, batch inserts, indexed time-range queries, and automatic retention cleanup
- **vad_metadata.py**: State machine managing 10 hotkey tags (timed 30s and persistent toggles) for speech scenarios, music, video, and ambient noise with conflict resolution
- **vad_hotkeys.py**: Non-blocking terminal keyboard input handler using select() for real-time hotkey capture without Enter key
- **vad_recommender.py**: Statistical analysis engine that analyzes RMS distributions, false positive rates, and pause patterns to recommend optimal noise_floor_threshold, silence_threshold, vad_aggressiveness, and silence_duration_seconds
- **vad_collector_config.ini**: Configuration for data collector with audio device, VAD parameters, database path, retention policy, and display settings
- **requirements_collector.txt**: Additional dependencies for collector/analyzer (matplotlib for visualizations, pandas for data processing)
- **README_VAD_TUNING.md**: Comprehensive usage guide with workflow, hotkey reference, analysis commands, troubleshooting, performance considerations, and best practices

### Documentation

- **ARCHITECTURE.md**: Comprehensive technical documentation covering audio pipeline, WebRTC VAD integration, silence detection algorithms, file lifecycle, and production deployment details
- **CODE_ANALYSIS.md**: Detailed code review analyzing logic flows, exception handling, security considerations, performance characteristics, and prioritized fix recommendations
- **ISSUES.md**: Actionable issue tracker with 6 prioritized items (1 critical, 1 major, 4 minor) - use this as a checklist for fixes
- **SILENCE_THRESHOLD.md**: Guide for tuning silence detection parameters
- **CLAUDE.md**: Development guidance and project architecture documentation

## Runtime Directory Structure

When the application runs, it creates the following structure in the configured storage directory:

```
/mnt/shared/raspi-audio/          # Configured storage directory (from config.ini)
├── .tmp/                         # Temporary directory for active recordings
│   ├── audio_YYYYMMDD_HHMMSS_NNkHz.{ext}  # Active recording files
│   └── .overlap_buffer.{ext}     # Temporary overlap buffer
├── audio_YYYYMMDD_HHMMSS_NNkHz.{ext}      # Completed recording files
├── vad_data.db                   # VAD metrics database (when collector is running)
├── vad_data.db-shm               # SQLite shared memory file (WAL mode)
├── vad_data.db-wal               # SQLite write-ahead log (WAL mode)
├── vad_collector.log             # VAD collector log file (if configured)
└── .write_test                   # Temporary file for write permission validation
```

### Temporary Directory (.tmp)
- Created automatically within the storage directory
- Used for active recordings and overlap processing
- Files are moved to parent directory only when recording is complete
- Automatically cleaned up on shutdown or failure
- Prevents partial recordings from appearing in the output directory