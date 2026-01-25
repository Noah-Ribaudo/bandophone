# Android Build Setup

## Prerequisites

### 1. Install Java (JDK 17+)

```bash
# macOS with Homebrew
brew install openjdk@17

# Add to PATH
echo 'export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 2. Set ANDROID_HOME

```bash
# If Android SDK is at ~/Library/Android/sdk
echo 'export ANDROID_HOME=~/Library/Android/sdk' >> ~/.zshrc
echo 'export PATH="$ANDROID_HOME/platform-tools:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 3. Accept Android SDK Licenses

```bash
yes | sdkmanager --licenses
```

## Building

```bash
cd android
./gradlew assembleDebug
```

APK will be at: `app/build/outputs/apk/debug/app-debug.apk`

## Installing

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Testing Audio Injection

1. Start the app and tap "Start Service"
2. Make a phone call
3. From a computer on the same network:

```bash
# Send test audio to the app
cat test_audio.raw | nc <phone_ip> 9999
```

Or via ADB port forwarding:

```bash
adb forward tcp:9999 tcp:9999
cat test_audio.raw | nc localhost 9999
```

## Troubleshooting

### "Permission denied" errors
Grant all requested permissions in Android Settings > Apps > Bandophone

### Audio not heard in call
The VOICE_COMMUNICATION usage may require the app to be a system app or have
special privileges. Try:
- Running with root: `su -c 'am start-service ...'`
- Modifying SELinux: `setenforce 0`
- Installing as system app in /system/priv-app/
