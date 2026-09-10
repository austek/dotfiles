#!/bin/bash

echo "--- Clipboard Detection Diagnostic ---"

if [ -n "$WAYLAND_DISPLAY" ]; then
    echo "Environment: Wayland detected ($WAYLAND_DISPLAY)"
elif [ -n "$DISPLAY" ]; then
    echo "Environment: X11 detected ($DISPLAY)"
else
    echo "Environment: Headless or Unknown (No DISPLAY vars set)"
fi

echo -n "Tools: "
TOOLS_FOUND=0
if command -v wl-copy >/dev/null; then echo -n "[wl-clipboard] "; TOOLS_FOUND=1; fi
if command -v xclip >/dev/null;   then echo -n "[xclip] "; TOOLS_FOUND=1; fi
if command -v xsel >/dev/null;    then echo -n "[xsel] "; TOOLS_FOUND=1; fi
if command -v pbcopy >/dev/null;  then echo -n "[macos-pbcopy] "; TOOLS_FOUND=1; fi

if [ $TOOLS_FOUND -eq 0 ]; then
    echo "NONE FOUND"
    echo "❌ Error: No clipboard utilities installed."
    exit 1
else
    echo ""
fi

TEST_STRING="Clipboard_Test_$(date +%s)"

echo -n "Test: Attempting to copy '$TEST_STRING'..."

if command -v pbcopy >/dev/null 2>&1; then
    echo "$TEST_STRING" | pbcopy
elif [ -n "$WAYLAND_DISPLAY" ] && command -v wl-copy >/dev/null 2>&1; then
    echo "$TEST_STRING" | wl-copy
elif [ -n "$DISPLAY" ] && command -v xclip >/dev/null 2>&1; then
    echo "$TEST_STRING" | xclip -selection clipboard
elif [ -n "$DISPLAY" ] && command -v xsel >/dev/null 2>&1; then
    echo "$TEST_STRING" | xsel --clipboard --input
else
    echo "❌ Failed: Could not map environment to a tool."
    exit 1
fi

echo " Done."
echo "Action: Please press CTRL+V (or CMD+V) below to verify:"
echo "---------------------------------------------------"
