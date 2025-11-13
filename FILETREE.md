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
├── config.ini                          # Configuration file with audio/recording settings
├── config.ini.example                  # Example configuration file
├── install-raspi-audio-recorder.sh     # Installation script for systemd service
├── py-arecord.md                       # Additional project documentation
├── raspi-audio-recorder.service        # systemd service unit file
├── raspi_audio_recorder.py             # Main application - audio recording service
├── requirements.txt                    # Python dependencies (webrtcvad)
└── SILENCE_THRESHOLD.md                # Guide for tuning silence detection parameters
```

## Key Files

- **raspi_audio_recorder.py**: Core Python application with WebRTC VAD, continuous audio recording, speech detection, and file management
- **config.ini**: Configuration file with audio device, VAD settings, compression format, sample rate, and recording parameters
- **config.ini.example**: Example configuration with documented settings
- **requirements.txt**: Python dependencies (webrtcvad for speech detection)
- **ARCHITECTURE.md**: Comprehensive technical documentation covering audio pipeline, WebRTC VAD integration, silence detection algorithms, file lifecycle, and production deployment details
- **CODE_ANALYSIS.md**: Detailed code review analyzing logic flows, exception handling, security considerations, performance characteristics, and prioritized fix recommendations
- **ISSUES.md**: Actionable issue tracker with 6 prioritized items (1 critical, 1 major, 4 minor) - use this as a checklist for fixes
- **install-raspi-audio-recorder.sh**: Installation script that deploys the service, configures systemd, and sets up permissions
- **raspi-audio-recorder.service**: systemd service configuration for daemon operation
- **CLAUDE.md**: Development guidance and project architecture documentation

## Runtime Directory Structure

When the application runs, it creates the following structure in the configured storage directory:

```
/hddzfs/raspi-audio/              # Configured storage directory (from config.ini)
├── .tmp/                         # Temporary directory for active recordings
│   ├── audio_YYYYMMDD_HHMMSS_NNkHz.{ext}  # Active recording files
│   └── .overlap_buffer.{ext}     # Temporary overlap buffer
├── audio_YYYYMMDD_HHMMSS_NNkHz.{ext}      # Completed recording files
└── .write_test                   # Temporary file for write permission validation
```

### Temporary Directory (.tmp)
- Created automatically within the storage directory
- Used for active recordings and overlap processing
- Files are moved to parent directory only when recording is complete
- Automatically cleaned up on shutdown or failure
- Prevents partial recordings from appearing in the output directory