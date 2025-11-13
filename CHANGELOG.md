# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **ARCHITECTURE.md**: Comprehensive technical documentation describing audio capture pipeline, WebRTC VAD integration, silence detection system, file management, and production deployment configuration
- **CODE_ANALYSIS.md**: Detailed code review identifying logic flaws, exception handling gaps, security considerations, and performance analysis with prioritized recommendations (updated to reflect recent fixes)
- **ISSUES.md**: Actionable issue tracker with prioritized list of bugs, improvements, and edge cases to address (6 issues total: 1 critical, 1 major, 4 minor)
- Lossless compression support with configurable format option (wav, flac, alac, ape)
- Sample rate included in filename format (e.g., `audio_20241201_143025_44kHz.flac`)
- Compression format configuration in `config.ini`
- Temporary folder recording with atomic file moves for data integrity
- **WebRTC VAD integration** for intelligent speech vs. noise detection
- Two-stage detection: RMS pre-filter + WebRTC VAD for efficient CPU usage
- Configurable VAD aggressiveness (0-3) and frame duration (10/20/30ms)
- Fallback to RMS-only detection if VAD unavailable or disabled
- Python-based real-time audio level monitoring for precise silence detection
- Minimum recording duration enforcement via `min_duration_seconds` configuration parameter (default: 45 seconds)
- Silence detection is disabled until minimum duration is reached, then activates automatically
- System waits for speech, records for at least min_duration, then stops on silence/non-speech detection
- If speech continues beyond minimum duration, recording continues until silence is detected
- Filters out door slams, machinery noise, and other non-speech sounds automatically

### Fixed
- Service file now uses storage directory from `config.ini` instead of hardcoded `/mnt/shared/raspi-audio`
- Install script now uses `config.ini` values by default without prompting (only prompts to change if explicitly requested)
- Added placeholder substitution for `ReadWritePaths` in systemd service file to match configured storage directory
- **Critical fix**: Recording loop no longer exits immediately on partial audio chunks (was causing rapid start/stop cycle with empty files)
- **Critical fix**: Sox command-line argument order corrected (compression flag now before output filename, not after)
- **Critical fix**: Added channel validation for WebRTC VAD (mono only) - prevents runtime crashes with stereo audio configurations
- Added comprehensive error logging for arecord and sox process failures with stderr capture
- Added debug logging for VAD frame sizes, chunk sizes, and actual command-line arguments
- Added audio device accessibility test before starting recording loop
- Added startup delay and process validation to catch immediate failures
- Added exponential backoff for consecutive recording failures (prevents tight error loops)
- Improved process termination order (arecord → sox) to prevent SIGPIPE warnings
- VAD processing errors now logged at WARNING level instead of DEBUG for better visibility
- Added VAD frame size validation to catch odd byte counts with non-standard sample rates
- Extracted magic number (1000 bytes) to named constant MIN_VALID_FILE_SIZE for clarity

### Changed
- **Silence detection architecture**: Moved from SoX-based to Python-based real-time audio level monitoring
- Filename format now includes sample rate: `audio_YYYYMMDD_HHMMSS_NNkHz.{ext}`
- Overlap buffer files now use the same compression format as recordings
- SoX compression flags automatically applied for non-WAV formats
- Recordings are now created in a temporary directory first, then moved to final location when complete
- Overlap buffers are now stored in temporary directory during processing
- Improved cleanup of temporary files on shutdown or failure
- Audio processing now reads raw PCM data for level analysis before writing to final format

### Technical Notes
- Requires SoX with appropriate codec support for chosen compression format
- File extensions automatically match the configured compression format
- Overlap buffer handling updated to support all compression formats
- Temporary directory (.tmp) created within storage directory for atomic operations
- Prevents partial files from appearing in output directory during recording