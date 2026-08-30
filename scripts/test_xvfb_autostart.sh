#!/usr/bin/env bash
# Test script to verify Xvfb auto-start functionality
set -euo pipefail

echo "=== Testing Xvfb Auto-Start Functionality ==="
echo

# Save original DISPLAY
ORIGINAL_DISPLAY="${DISPLAY:-}"
ORIGINAL_WAYLAND="${WAYLAND_DISPLAY:-}"

# Test 1: Simulate Wayland environment (no X11)
echo "Test 1: Simulating Wayland environment (no DISPLAY)..."
unset DISPLAY
export WAYLAND_DISPLAY="wayland-0"

# Start runtime in background
echo "Starting runtime_server..."
python -m platforms.linux.guest.runtime_server --port 5001 > /tmp/test_xvfb_runtime.log 2>&1 &
RUNTIME_PID=$!

# Wait for startup
echo "Waiting for runtime to start..."
sleep 5

# Check if Xvfb was started
if pgrep -f "Xvfb :99" > /dev/null; then
    echo "✓ Xvfb process found"
else
    echo "✗ Xvfb process NOT found"
    cat /tmp/test_xvfb_runtime.log
    kill $RUNTIME_PID 2>/dev/null || true
    exit 1
fi

# Test screenshot endpoint
echo "Testing screenshot endpoint..."
if curl -s -f http://localhost:5001/screenshot -o /tmp/test_screenshot.png; then
    if file /tmp/test_screenshot.png | grep -q "PNG image"; then
        echo "✓ Screenshot endpoint working (valid PNG)"
        
        # Check image size
        SIZE=$(identify -format "%wx%h" /tmp/test_screenshot.png 2>/dev/null || echo "unknown")
        echo "  Screenshot size: $SIZE"
    else
        echo "✗ Screenshot endpoint returned invalid image"
        file /tmp/test_screenshot.png
        kill $RUNTIME_PID 2>/dev/null || true
        pkill -f "Xvfb :99" || true
        exit 1
    fi
else
    echo "✗ Screenshot endpoint failed"
    cat /tmp/test_xvfb_runtime.log
    kill $RUNTIME_PID 2>/dev/null || true
    pkill -f "Xvfb :99" || true
    exit 1
fi

# Cleanup
echo "Cleaning up..."
kill $RUNTIME_PID 2>/dev/null || true
sleep 2

# Verify Xvfb was cleaned up
if pgrep -f "Xvfb :99" > /dev/null; then
    echo "✗ Xvfb process still running after cleanup"
    pkill -f "Xvfb :99" || true
    exit 1
else
    echo "✓ Xvfb cleaned up properly"
fi

# Restore original environment
if [ -n "$ORIGINAL_DISPLAY" ]; then
    export DISPLAY="$ORIGINAL_DISPLAY"
else
    unset DISPLAY
fi

if [ -n "$ORIGINAL_WAYLAND" ]; then
    export WAYLAND_DISPLAY="$ORIGINAL_WAYLAND"
else
    unset WAYLAND_DISPLAY 2>/dev/null || true
fi

echo
echo "=== All Tests Passed ==="
echo
echo "Xvfb auto-start is working correctly!"
