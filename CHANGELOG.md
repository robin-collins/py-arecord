# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Lossless compression support with configurable format option (wav, flac, alac, ape)
- Sample rate included in filename format (e.g., `audio_20241201_143025_44kHz.flac`)
- Compression format configuration in `config.ini`
- Temporary folder recording with atomic file moves for data integrity

### Changed
- Filename format now includes sample rate: `audio_YYYYMMDD_HHMMSS_NNkHz.{ext}`
- Overlap buffer files now use the same compression format as recordings
- SoX compression flags automatically applied for non-WAV formats
- Recordings are now created in a temporary directory first, then moved to final location when complete
- Overlap buffers are now stored in temporary directory during processing
- Improved cleanup of temporary files on shutdown or failure

### Technical Notes
- Requires SoX with appropriate codec support for chosen compression format
- File extensions automatically match the configured compression format
- Overlap buffer handling updated to support all compression formats
- Temporary directory (.tmp) created within storage directory for atomic operations
- Prevents partial files from appearing in output directory during recording