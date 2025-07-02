# Audio Recorder Service for Raspberry Pi

## 1. **Overview**

Develop a Python-based audio recording service for Raspberry Pi, capturing from a specified ALSA device, continuously segmenting audio based on silence detection, ensuring no loss of conversation, and storing recordings in a shared directory with robust file management and error handling. The service must run as a reliable `systemd` daemon.

---

## 2. **Requirements**

### 2.1 **Core Functional Requirements**

* **Continuous Recording:**
  Continuously record audio from a specified ALSA device.
* **Silence-Based Segmentation:**
  Automatically split recordings at silence boundaries using appropriate algorithms to avoid cutting off speech. Each segment should have a maximum intended duration (e.g., 60 minutes), but should allow extra recording to finish an ongoing speech segment.
* **Overlap Handling:**
  Ensure the end of each recording is overlapped at the start of the next segment (e.g., last 5 minutes), so conversation is not lost or split awkwardly.
* **File Naming and Safety:**
  Save each segment as a WAV file named with date/time (UTC) in the format `audio_YYYYMMDD_HHMMSS.wav`. If a file with the same name exists, append `_vN` to avoid overwrite.
* **Storage Location:**
  Recordings are saved to `/mnt/shared/raspi-audio`.

### 2.2 **Robustness and Error Handling**

* **Graceful Handling:**
  Handle all runtime errors (e.g., device not found, disk full, permission issues, unexpected ALSA or SoX errors) with retries and clear error logging.
* **Safe Exit:**
  Handle `SIGINT` (Ctrl+C), `SIGTERM`, and other signals gracefully, closing files and freeing resources before exit.
* **Startup Checks:**
  Validate audio device, recording path existence/writability, and external tool dependencies (e.g., SoX) at startup; provide clear logs for any issues.

### 2.3 **System Integration**

* **Systemd Service:**
  Provide a robust `systemd` unit file and install instructions to ensure the script auto-starts on boot, restarts on failure, and logs to the system journal.
* **Logging:**
  Log significant events, errors, and status messages to both console (when run interactively) and systemd journal.

### 2.4 **Configuration**

* **Config File:**
  Allow configuration of:

  * Audio device name
  * Maximum intended segment duration
  * Overlap duration
  * Storage directory
  * Silence detection sensitivity (if applicable)

### 2.5 **Dependencies**

* Python 3.7+
* [SoX](http://sox.sourceforge.net/) (invoked via subprocess for silence detection and splitting)
* ALSA audio stack

---

## 3. **Non-Functional Requirements**

* **Resource Efficiency:**
  Must run reliably for months unattended on Raspberry Pi 4B.
* **Fault Tolerance:**
  Must handle transient errors and resume operation without manual intervention.
* **Security:**
  Only write to configured storage directory; avoid temporary files elsewhere.

---

## 4. **Deliverables**

1. Python application (`raspi_audio_recorder.py`)
2. Example configuration file (`config.ini` or `.yaml`)
3. systemd service unit file (`raspi-audio-recorder.service`)
4. Installation and usage instructions (`README.md`)
5. Logging and troubleshooting documentation
