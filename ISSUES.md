# Open Issues - raspi_audio_recorder.py

**Last Updated**: 2025-01-13
**Status**: 1 Critical, 1 Major, 4 Minor

This document tracks open issues, bugs, and improvements needed in the codebase. Issues are prioritized by severity and impact.

---

## ❌ Critical Issues (Must Fix Before Production)

### Issue #1: Missing Channel Validation for VAD

**Severity**: CRITICAL
**Priority**: HIGH
**Impact**: Runtime crash with stereo audio + VAD enabled
**Location**: `raspi_audio_recorder.py:107-162` (`_setup_vad()` method)

**Description**:
WebRTC VAD only supports mono audio (1 channel). If a user configures `channels = 2` with `use_vad = true`, the VAD will fail at runtime with cryptic errors from the webrtcvad library.

**Current Behavior**:
- VAD validates sample rate ✓
- VAD validates frame duration ✓
- VAD validates aggressiveness ✓
- VAD does NOT validate channel count ❌

**Expected Behavior**:
When VAD is enabled and channels != 1, the service should:
1. Log a clear warning message
2. Automatically disable VAD
3. Fall back to RMS-only detection
4. Continue running without crashing

**Proposed Fix**:
```python
def _setup_vad(self):
    """Initialize WebRTC VAD if enabled and available."""
    self.vad = None
    self.use_vad = self.config["use_vad"]

    if self.use_vad:
        if not WEBRTCVAD_AVAILABLE:
            self.logger.warning(
                "WebRTC VAD requested but not available. "
                "Install with: pip install webrtcvad. "
                "Falling back to RMS-only detection."
            )
            self.use_vad = False
            return

        # ADD THIS SECTION (after line 120, before sample rate validation):
        # Validate channels (WebRTC VAD requires mono)
        channels = self.config["channels"]
        if channels != 1:
            self.logger.warning(
                f"WebRTC VAD requires mono audio (channels=1), got channels={channels}. "
                f"Falling back to RMS-only detection."
            )
            self.use_vad = False
            return

        # Existing sample rate validation continues...
        valid_sample_rates = [8000, 16000, 32000, 48000]
        sample_rate = self.config["sample_rate"]
        if sample_rate not in valid_sample_rates:
            ...
```

**Where to Add**: After line 120 (after `WEBRTCVAD_AVAILABLE` check), before sample rate validation

**Test Cases**:
1. Set `channels = 2` and `use_vad = true` in config
2. Start service
3. Verify warning logged: "WebRTC VAD requires mono audio..."
4. Verify service falls back to RMS detection
5. Verify service continues running without crash

**Estimated Effort**: 10 minutes
**Risk**: Low (simple validation with fallback)

---

## ⚠️ Major Issues (Should Fix)

### Issue #2: Suboptimal Process Termination Order

**Severity**: MAJOR
**Priority**: MEDIUM
**Impact**: Possible SIGPIPE warnings in logs, no functional impact
**Location**: `raspi_audio_recorder.py:583-595` (`_record_segment()` method)

**Description**:
Currently, sox's stdin is closed before terminating arecord. This means arecord might still be writing data when sox's stdin closes, potentially causing SIGPIPE errors (though Python handles these gracefully).

**Current Code**:
```python
# Clean shutdown
if sox_proc.stdin:
    sox_proc.stdin.close()  # Close sox stdin FIRST

arecord_proc.terminate()     # Then terminate arecord
sox_proc.terminate()

try:
    arecord_proc.wait(timeout=5)
    sox_proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    arecord_proc.kill()
    sox_proc.kill()
```

**Issue**:
If arecord has buffered data in its stdout, closing sox's stdin first might cause:
- SIGPIPE signal to arecord
- Warning messages in logs
- No data corruption (Python handles SIGPIPE gracefully)

**Proposed Fix**:
```python
# Clean shutdown - terminate data source first
arecord_proc.terminate()
try:
    arecord_proc.wait(timeout=2)
except subprocess.TimeoutExpired:
    self.logger.warning("arecord did not terminate gracefully, killing...")
    arecord_proc.kill()
    try:
        arecord_proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass  # Process is dead

# Then close sink and terminate sox
if sox_proc.stdin:
    try:
        sox_proc.stdin.close()
    except Exception as e:
        self.logger.debug(f"Error closing sox stdin: {e}")

sox_proc.terminate()
try:
    sox_proc.wait(timeout=3)
except subprocess.TimeoutExpired:
    self.logger.warning("sox did not terminate gracefully, killing...")
    sox_proc.kill()
```

**Benefits**:
- Cleaner shutdown sequence (source → sink)
- Fewer warnings in logs
- More predictable behavior

**Test Cases**:
1. Normal recording stop (via silence detection)
2. Emergency stop (max duration reached)
3. Signal-based stop (SIGTERM)
4. Verify no SIGPIPE errors in logs

**Estimated Effort**: 30 minutes
**Risk**: Low (improves existing shutdown logic)

---

## ℹ️ Minor Issues (Nice to Have)

### Issue #3: VAD Exception Logging Level Too Low

**Severity**: MINOR
**Priority**: LOW
**Impact**: VAD errors hidden at INFO log level
**Location**: `raspi_audio_recorder.py:323-324` (`_check_for_speech()` method)

**Description**:
When VAD processing fails, the exception is logged at DEBUG level. This means it won't appear when running at INFO level, making troubleshooting harder.

**Current Code**:
```python
except Exception as e:
    self.logger.debug(f"VAD error: {e}, falling back to RMS")
```

**Proposed Fix**:
```python
except Exception as e:
    self.logger.warning(
        f"VAD processing error (chunk size: {len(audio_chunk)} bytes): {e}. "
        f"Falling back to RMS threshold."
    )
```

**Benefits**:
- Visible at INFO log level
- Better debugging information
- Alerts operators to VAD issues

**Estimated Effort**: 5 minutes
**Risk**: None

---

### Issue #4: Magic Number for File Size Validation

**Severity**: MINOR
**Priority**: LOW
**Impact**: Code readability
**Location**: `raspi_audio_recorder.py:600` (`_record_segment()` method)

**Description**:
Hard-coded `1000` bytes minimum file size makes the threshold arbitrary and unclear.

**Current Code**:
```python
if os.path.exists(temp_file) and os.path.getsize(temp_file) > 1000:
```

**Proposed Fix**:
```python
# At class level or module level:
MIN_VALID_FILE_SIZE = 1000  # bytes - minimum for valid audio file header + some data

# In _record_segment():
if os.path.exists(temp_file) and os.path.getsize(temp_file) > MIN_VALID_FILE_SIZE:
```

**Benefits**:
- Self-documenting code
- Easy to adjust threshold
- Clear intent

**Estimated Effort**: 5 minutes
**Risk**: None

---

### Issue #5: VAD Frame Size Integer Division Edge Case

**Severity**: MINOR
**Priority**: LOW
**Impact**: Potential issue with non-standard sample rates
**Location**: `raspi_audio_recorder.py:470-472` (`_record_segment()` method)

**Description**:
VAD frame size calculation uses integer division without validating the result is even.

**Current Code**:
```python
vad_frame_duration_ms = self.config["vad_frame_duration_ms"]
vad_frame_size = (sample_rate * vad_frame_duration_ms // 1000) * channels * 2
```

**Analysis**:
- For standard rates (8000/16000/32000/48000), this always produces even numbers ✓
- For non-standard rates, could theoretically produce odd byte counts
- Odd byte counts would be invalid for 16-bit PCM (2 bytes per sample)

**Proposed Fix**:
```python
vad_frame_duration_ms = self.config["vad_frame_duration_ms"]
vad_frame_size = (sample_rate * vad_frame_duration_ms // 1000) * channels * 2

# Validate frame size is even (required for 16-bit PCM)
if vad_frame_size % 2 != 0:
    self.logger.error(
        f"Invalid VAD frame size: {vad_frame_size} bytes (not even). "
        f"Sample rate {sample_rate} Hz incompatible with VAD. "
        f"Falling back to RMS-only detection."
    )
    self.use_vad = False
    vad_frame_size = sample_rate * channels * 2  # Use 1-second chunks instead
```

**Note**: This is highly unlikely to occur in practice since VAD already validates sample rates.

**Estimated Effort**: 10 minutes
**Risk**: None


## 📋 Issue Summary

| Issue # | Title | Severity | Priority | Effort | Status |
|---------|-------|----------|----------|--------|--------|
| #1 | Missing Channel Validation for VAD | CRITICAL | HIGH | 10 min | Open |
| #2 | Suboptimal Process Termination Order | MAJOR | MEDIUM | 30 min | Open |
| #3 | VAD Exception Logging Level Too Low | MINOR | LOW | 5 min | Open |
| #4 | Magic Number for File Size | MINOR | LOW | 5 min | Open |
| #5 | VAD Frame Size Integer Division | MINOR | LOW | 10 min | Open |

**Total Estimated Effort**: ~1.5 hours

---

## 🎯 Recommended Action Plan

### Phase 1: Critical Fixes (Before Production Deploy)
1. **Issue #1**: Add channel validation for VAD ⚠️ **REQUIRED**

### Phase 2: Quality Improvements (Next Sprint)
2. **Issue #2**: Fix process termination order
3. **Issue #3**: Improve VAD error logging
4. **Issue #4**: Extract magic numbers to constants

### Phase 3: Edge Cases (Future Improvements)
5. **Issue #5**: Add VAD frame size validation

---

## 📝 Notes

### Testing Checklist
After fixing Issue #1, verify:
- [ ] Mono audio with VAD enabled works
- [ ] Stereo audio with VAD enabled falls back to RMS
- [ ] Warning message is logged for stereo + VAD
- [ ] Service continues running (no crash)
- [ ] Recordings are created successfully in RMS mode

### Related Files
- **Main Code**: `raspi_audio_recorder.py`
- **Config**: `config.ini`
- **Tests**: (Need to create test suite)
- **Docs**: `ARCHITECTURE.md`, `CODE_ANALYSIS.md`

---

## ✅ Recently Fixed Issues

For reference, these issues were fixed in recent updates:

- ✅ **SoX command-line argument order** (compression flag placement)
- ✅ **Audio device accessibility test** (pre-test before recording)
- ✅ **Process startup validation** (catch immediate failures)
- ✅ **Exponential backoff** (prevent tight error loops)
- ✅ **Debug command logging** (troubleshooting support)

See `CODE_ANALYSIS.md` for detailed analysis of these fixes.
