#!/bin/bash
#
# Voxbridge Diagnostic Script
# Run this while a call is active to discover audio routing
#

set -e

echo "═══════════════════════════════════════════════════════"
echo "  Voxbridge Audio Diagnostics"
echo "═══════════════════════════════════════════════════════"
echo ""

# Check for ADB
if ! command -v adb &> /dev/null; then
    echo "❌ ADB not found. Please install Android SDK platform-tools."
    exit 1
fi

# Check device connection
DEVICE=$(adb devices | grep -v "List" | grep "device$" | head -1 | cut -f1)
if [ -z "$DEVICE" ]; then
    echo "❌ No Android device connected via ADB."
    echo "   Connect your device and enable USB debugging."
    exit 1
fi

echo "📱 Device: $DEVICE"
echo ""

# Check root
echo "🔐 Checking root access..."
if ! adb shell "su -c 'id'" 2>/dev/null | grep -q "uid=0"; then
    echo "❌ Root access not available. Voxbridge requires a rooted device."
    exit 1
fi
echo "✅ Root access confirmed"
echo ""

# Get device info
echo "📋 Device Information"
echo "─────────────────────────────────────────────────────────"
adb shell "getprop ro.product.model"
adb shell "getprop ro.product.device"
adb shell "getprop ro.build.version.release"
adb shell "getprop ro.hardware"
echo ""

# Check SELinux
echo "🛡️  SELinux Status"
echo "─────────────────────────────────────────────────────────"
SELINUX=$(adb shell "su -c 'getenforce'" 2>/dev/null | tr -d '\r')
echo "Mode: $SELINUX"
if [ "$SELINUX" = "Enforcing" ]; then
    echo "⚠️  SELinux is Enforcing. You may need to set it to Permissive:"
    echo "   adb shell 'su -c setenforce 0'"
fi
echo ""

# List sound cards
echo "🎵 Sound Cards"
echo "─────────────────────────────────────────────────────────"
adb shell "su -c 'cat /proc/asound/cards'" 2>/dev/null || echo "(not available)"
echo ""

# List PCM devices
echo "🎤 PCM Devices"
echo "─────────────────────────────────────────────────────────"
adb shell "su -c 'cat /proc/asound/pcm'" 2>/dev/null || echo "(not available)"
echo ""

# Check for tinyalsa binaries
echo "🔧 TinyALSA Binaries"
echo "─────────────────────────────────────────────────────────"
for bin in tinymix tinycap tinyplay tinypcminfo; do
    for path in /system/bin /vendor/bin /data/local/tmp; do
        if adb shell "su -c 'test -f $path/$bin && echo found'" 2>/dev/null | grep -q "found"; then
            echo "✅ $bin: $path/$bin"
            break
        fi
    done
done
echo ""

# Check active PCM streams (important during a call!)
echo "📞 Active PCM Streams (run this during a call!)"
echo "─────────────────────────────────────────────────────────"
adb shell "su -c 'for f in /proc/asound/card*/pcm*/sub*/status; do echo \"=== \$f ===\"; cat \"\$f\" 2>/dev/null; done'" 2>/dev/null | head -100
echo ""

# Dump mixer controls (if tinymix available)
echo "🎚️  Mixer Controls (searching for voice/call related)"
echo "─────────────────────────────────────────────────────────"
TINYMIX=$(adb shell "su -c 'which tinymix 2>/dev/null || echo /vendor/bin/tinymix'" | tr -d '\r')
if adb shell "su -c 'test -f $TINYMIX && echo found'" 2>/dev/null | grep -q "found"; then
    adb shell "su -c '$TINYMIX'" 2>/dev/null | grep -iE "(voice|call|incall|record|capture|uplink|downlink|modem)" | head -50
    echo ""
    echo "(Full mixer dump saved to mixer_full.txt)"
    adb shell "su -c '$TINYMIX'" > mixer_full.txt 2>/dev/null
else
    echo "⚠️  tinymix not found. Consider installing tinyalsa."
fi
echo ""

# Audio policy
echo "📜 Audio Policy Configuration"
echo "─────────────────────────────────────────────────────────"
for policy in /vendor/etc/audio_policy_configuration.xml /system/etc/audio_policy_configuration.xml; do
    if adb shell "su -c 'test -f $policy && echo found'" 2>/dev/null | grep -q "found"; then
        echo "Found: $policy"
        echo "Extracting voice/telephony sections..."
        adb shell "su -c 'cat $policy'" 2>/dev/null | grep -iE "(telephony|voice|call)" | head -20
    fi
done
echo ""

echo "═══════════════════════════════════════════════════════"
echo "  Diagnostics Complete"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "📝 Next Steps:"
echo "   1. If no call was active, make a call and run this again"
echo "   2. Check mixer_full.txt for all available controls"
echo "   3. Look for PCM devices with 'voice' or 'incall' in the name"
echo "   4. Share your findings at github.com/[your-repo]/voxbridge"
echo ""
