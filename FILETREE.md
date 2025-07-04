# File Tree

```
py-arecord/
├── CHANGELOG.md                    # Project changelog
├── CLAUDE.md                       # Claude Code guidance
├── FILETREE.md                     # This file tree documentation
├── README.md                       # Project documentation
├── config.ini                     # Configuration file with audio/recording settings
├── py-arecord.md                   # Additional project documentation
├── raspi-audio-recorder.service    # systemd service unit file
└── raspi_audio_recorder.py         # Main application - audio recording service
```

## Key Files

- **raspi_audio_recorder.py**: Core Python application with continuous audio recording, silence detection, and file management
- **config.ini**: Configuration file with audio device, compression format, sample rate, and recording parameters
- **raspi-audio-recorder.service**: systemd service configuration for daemon operation
- **CLAUDE.md**: Development guidance and project architecture documentation

## Runtime Directory Structure

When the application runs, it creates the following structure in the configured storage directory:

```
/mnt/shared/raspi-audio/          # Default storage directory
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