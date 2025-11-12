#!/usr/bin/env bash
# Raspberry Pi Audio Recorder - Installation Script
# Usage: ./install.sh [install|update|remove]

set -e  # Exit on error

__version__="1.0.0"

# Configuration variables
INSTALL_DIR="/opt/raspi-audio-recorder"
STORAGE_DIR="/hddzfs/raspi-audio"
SERVICE_NAME="raspi-audio-recorder"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEM_USER="${USER:-pi}"
AUDIO_GROUP="audio"

# Parse config.ini for storage directory if it exists
parse_config_storage() {
    if [ -f "config.ini" ]; then
        local storage_dir
        storage_dir=$(grep -A 10 '^\[storage\]' config.ini | grep '^directory' | cut -d'=' -f2 | xargs)
        if [ -n "$storage_dir" ]; then
            echo "$storage_dir"
        fi
    fi
}

# Override STORAGE_DIR with value from config.ini if available
CONFIG_STORAGE_DIR=$(parse_config_storage)
if [ -n "$CONFIG_STORAGE_DIR" ]; then
    STORAGE_DIR="$CONFIG_STORAGE_DIR"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_dependencies() {
    print_info "Checking system dependencies..."
    
    local missing_deps=()
    
    if ! command -v python3 &> /dev/null; then
        missing_deps+=("python3")
    fi
    
    if ! command -v sox &> /dev/null; then
        missing_deps+=("sox")
    fi
    
    if ! command -v arecord &> /dev/null; then
        missing_deps+=("alsa-utils")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_error "Missing dependencies: ${missing_deps[*]}"
        echo "Install them with: sudo apt update && sudo apt install ${missing_deps[*]}"
        exit 1
    fi
    
    print_info "All dependencies satisfied"
}

check_files() {
    local required_files=("raspi_audio_recorder.py" "config.ini" "${SERVICE_FILE}")
    local missing_files=()
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            missing_files+=("$file")
        fi
    done
    
    if [ ${#missing_files[@]} -ne 0 ]; then
        print_error "Missing required files: ${missing_files[*]}"
        print_info "Run this script from the project directory containing these files"
        exit 1
    fi
}

prompt_settings() {
    print_info "Configure installation settings"
    echo
    
    read -p "Installation directory [${INSTALL_DIR}]: " input
    INSTALL_DIR="${input:-$INSTALL_DIR}"
    
    read -p "Storage directory [${STORAGE_DIR}]: " input
    STORAGE_DIR="${input:-$STORAGE_DIR}"
    
    read -p "System user [${SYSTEM_USER}]: " input
    SYSTEM_USER="${input:-$SYSTEM_USER}"
    
    read -p "Audio group [${AUDIO_GROUP}]: " input
    AUDIO_GROUP="${input:-$AUDIO_GROUP}"
    
    echo
    print_info "Settings confirmed:"
    echo "  Installation directory: ${INSTALL_DIR}"
    echo "  Storage directory: ${STORAGE_DIR}"
    echo "  System user: ${SYSTEM_USER}"
    echo "  Audio group: ${AUDIO_GROUP}"
    echo
}

install_service() {
    print_info "Starting installation..."
    
    check_dependencies
    check_files
    
    # Create installation directory
    print_info "Creating installation directory: ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    
    # Copy application files
    print_info "Copying application files..."
    cp raspi_audio_recorder.py "${INSTALL_DIR}/"
    cp config.ini "${INSTALL_DIR}/"
    chmod +x "${INSTALL_DIR}/raspi_audio_recorder.py"
    
    # Set ownership
    if id "${SYSTEM_USER}" &>/dev/null; then
        chown -R "${SYSTEM_USER}:${SYSTEM_USER}" "${INSTALL_DIR}"
    else
        print_warn "User ${SYSTEM_USER} does not exist, skipping ownership change"
    fi
    
    # Create storage directory
    print_info "Creating storage directory: ${STORAGE_DIR}"
    mkdir -p "${STORAGE_DIR}"
    
    if id "${SYSTEM_USER}" &>/dev/null && getent group "${AUDIO_GROUP}" &>/dev/null; then
        chown "${SYSTEM_USER}:${AUDIO_GROUP}" "${STORAGE_DIR}"
        chmod 775 "${STORAGE_DIR}"
        
        # Add user to audio group
        usermod -a -G "${AUDIO_GROUP}" "${SYSTEM_USER}" 2>/dev/null || true
    else
        print_warn "User/group not found, using root ownership for storage directory"
        chmod 755 "${STORAGE_DIR}"
    fi
    
    # Update service file paths if needed
    print_info "Installing systemd service..."
    sed -e "s|/opt/raspi-audio-recorder|${INSTALL_DIR}|g" \
        -e "s|User=pi|User=${SYSTEM_USER}|g" \
        "${SERVICE_FILE}" > "/etc/systemd/system/${SERVICE_FILE}"
    
    chmod 644 "/etc/systemd/system/${SERVICE_FILE}"
    
    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
    
    print_info "Installation complete!"
    echo
    print_info "Next steps:"
    echo "  1. Edit configuration: ${INSTALL_DIR}/config.ini"
    echo "  2. List audio devices: arecord -l"
    echo "  3. Validate setup: python3 ${INSTALL_DIR}/raspi_audio_recorder.py --validate"
    echo "  4. Start service: sudo systemctl start ${SERVICE_NAME}"
    echo "  5. Check status: sudo systemctl status ${SERVICE_NAME}"
    echo "  6. View logs: sudo journalctl -u ${SERVICE_NAME} -f"
}

update_service() {
    print_info "Starting update..."
    
    if [ ! -d "${INSTALL_DIR}" ]; then
        print_error "Installation directory not found: ${INSTALL_DIR}"
        print_info "Run 'install' first"
        exit 1
    fi
    
    # Check if service is running
    local service_was_running=false
    if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        service_was_running=true
        print_info "Stopping service..."
        systemctl stop "${SERVICE_NAME}.service"
    fi
    
    # Prompt for updated settings
    echo
    read -p "Update installation settings? (y/N): " update_settings
    if [[ "$update_settings" =~ ^[Yy]$ ]]; then
        prompt_settings
        
        # Update service file
        print_info "Updating systemd service..."
        sed -e "s|/opt/raspi-audio-recorder|${INSTALL_DIR}|g" \
            -e "s|User=pi|User=${SYSTEM_USER}|g" \
            "${SERVICE_FILE}" > "/etc/systemd/system/${SERVICE_FILE}"
        
        systemctl daemon-reload
    fi
    
    # Backup existing config
    if [ -f "${INSTALL_DIR}/config.ini" ]; then
        print_info "Backing up existing configuration..."
        cp "${INSTALL_DIR}/config.ini" "${INSTALL_DIR}/config.ini.backup.$(date +%Y%m%d_%H%M%S)"
    fi
    
    # Copy updated files
    print_info "Copying updated files..."
    check_files
    cp raspi_audio_recorder.py "${INSTALL_DIR}/"
    chmod +x "${INSTALL_DIR}/raspi_audio_recorder.py"
    
    read -p "Overwrite config.ini? (y/N): " overwrite_config
    if [[ "$overwrite_config" =~ ^[Yy]$ ]]; then
        cp config.ini "${INSTALL_DIR}/"
    else
        print_info "Keeping existing config.ini (backup created)"
    fi
    
    # Set ownership
    if id "${SYSTEM_USER}" &>/dev/null; then
        chown -R "${SYSTEM_USER}:${SYSTEM_USER}" "${INSTALL_DIR}"
    fi
    
    # Restart service if it was running
    if [ "$service_was_running" = true ]; then
        print_info "Restarting service..."
        systemctl restart "${SERVICE_NAME}.service"
    fi
    
    print_info "Update complete!"
    echo
    print_info "Review changes:"
    echo "  - Check config: ${INSTALL_DIR}/config.ini"
    echo "  - Backup saved: ${INSTALL_DIR}/config.ini.backup.*"
    echo "  - View status: sudo systemctl status ${SERVICE_NAME}"
    echo "  - View logs: sudo journalctl -u ${SERVICE_NAME} -f"
}

remove_service() {
    print_info "Starting removal..."
    
    # Stop and disable service
    if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        print_info "Stopping service..."
        systemctl stop "${SERVICE_NAME}.service"
    fi
    
    if systemctl is-enabled --quiet "${SERVICE_NAME}.service" 2>/dev/null; then
        print_info "Disabling service..."
        systemctl disable "${SERVICE_NAME}.service"
    fi
    
    # Remove service file
    if [ -f "/etc/systemd/system/${SERVICE_FILE}" ]; then
        print_info "Removing systemd service file..."
        rm -f "/etc/systemd/system/${SERVICE_FILE}"
        systemctl daemon-reload
    fi
    
    # Remove installation directory
    if [ -d "${INSTALL_DIR}" ]; then
        print_info "Removing installation directory: ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    fi
    
    # Ask about storage directory
    if [ -d "${STORAGE_DIR}" ]; then
        echo
        print_warn "Storage directory contains recordings: ${STORAGE_DIR}"
        read -p "Remove storage directory and all recordings? (y/N): " remove_storage
        if [[ "$remove_storage" =~ ^[Yy]$ ]]; then
            print_info "Removing storage directory..."
            rm -rf "${STORAGE_DIR}"
        else
            print_info "Keeping storage directory: ${STORAGE_DIR}"
        fi
    fi
    
    print_info "Removal complete!"
    echo
    print_info "To completely remove dependencies:"
    echo "  sudo apt remove sox alsa-utils"
}

show_usage() {
    cat << EOF
Raspberry Pi Audio Recorder - Installation Script v${__version__}

Usage: sudo $0 [install|update|remove] [OPTIONS]

Commands:
    install     Install the audio recorder service
    update      Update the service (allows changing settings)
    remove      Remove the service and optionally data

Options:
    -h, --help              Show this help message
    --install-dir DIR       Set installation directory (default: ${INSTALL_DIR})
    --storage-dir DIR       Set storage directory (default: ${STORAGE_DIR})
    --user USER             Set system user (default: ${SYSTEM_USER})
    --audio-group GROUP     Set audio group (default: ${AUDIO_GROUP})
    --non-interactive       Skip prompts (use defaults)

Examples:
    sudo $0 install
    sudo $0 install --user pi --storage-dir /media/recordings
    sudo $0 update
    sudo $0 remove

EOF
}

# Parse command line arguments
NON_INTERACTIVE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        install|update|remove)
            ACTION="$1"
            shift
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --storage-dir)
            STORAGE_DIR="$2"
            shift 2
            ;;
        --user)
            SYSTEM_USER="$2"
            shift 2
            ;;
        --audio-group)
            AUDIO_GROUP="$2"
            shift 2
            ;;
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
if [ -z "${ACTION}" ]; then
    print_error "No action specified"
    show_usage
    exit 1
fi

check_root

case "${ACTION}" in
    install)
        if [ "$NON_INTERACTIVE" = false ]; then
            prompt_settings
            read -p "Proceed with installation? (Y/n): " confirm
            if [[ "$confirm" =~ ^[Nn]$ ]]; then
                print_info "Installation cancelled"
                exit 0
            fi
        fi
        install_service
        ;;
    update)
        update_service
        ;;
    remove)
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Are you sure you want to remove the service? (y/N): " confirm
            if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
                print_info "Removal cancelled"
                exit 0
            fi
        fi
        remove_service
        ;;
    *)
        print_error "Invalid action: ${ACTION}"
        show_usage
        exit 1
        ;;
esac

exit 0