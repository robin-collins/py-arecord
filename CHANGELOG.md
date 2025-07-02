# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Lossless compression support with configurable format option (wav, flac, alac, ape)
- Sample rate included in filename format (e.g., `audio_20241201_143025_44kHz.flac`)
- Compression format configuration in `config.yaml`

### Changed
- Filename format now includes sample rate: `audio_YYYYMMDD_HHMMSS_NNkHz.{ext}`
- Overlap buffer files now use the same compression format as recordings
- SoX compression flags automatically applied for non-WAV formats

### Technical Notes
- Requires SoX with appropriate codec support for chosen compression format
- File extensions automatically match the configured compression format
- Overlap buffer handling updated to support all compression formats