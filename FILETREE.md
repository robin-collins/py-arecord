# File Tree

```
py-arecord/
├── CHANGELOG.md                    # Project changelog
├── CLAUDE.md                       # Claude Code guidance
├── FILETREE.md                     # This file tree documentation
├── README.md                       # Project documentation
├── config.yaml                     # Configuration file with audio/recording settings
├── py-arecord.md                   # Additional project documentation
├── raspi-audio-recorder.service    # systemd service unit file
└── raspi_audio_recorder.py         # Main application - audio recording service
```

## Key Files

- **raspi_audio_recorder.py**: Core Python application with continuous audio recording, silence detection, and file management
- **config.yaml**: Configuration file with audio device, compression format, sample rate, and recording parameters
- **raspi-audio-recorder.service**: systemd service configuration for daemon operation
- **CLAUDE.md**: Development guidance and project architecture documentation