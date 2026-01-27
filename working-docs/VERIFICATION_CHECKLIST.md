# Integration Verification Checklist

## Code Review Results ✅

### Manifest Validation
- ✅ All required permissions present (RECORD_AUDIO, MODIFY_AUDIO_SETTINGS, BIND_INCALL_SERVICE)
- ✅ BandoInCallService properly registered with correct intent filter
- ✅ SettingsActivity registered
- ✅ Service exported correctly with proper permissions
- ✅ Meta-data for InCallService UI present

### Kotlin Code Validation
- ✅ Package names consistent
- ✅ Import statements complete
- ✅ No obvious syntax errors
- ✅ Proper null safety handling
- ✅ Coroutine scoping correct
- ✅ Lifecycle management proper

### Dependencies
- ✅ OkHttp 4.12.0 present (for WebSocket)
- ✅ Coroutines 1.7.3 present
- ✅ EncryptedSharedPreferences added (security-crypto:1.1.0-alpha06)
- ✅ Compose dependencies already present
- ✅ Material 3 components available

### Security
- ✅ API key encrypted with AES256_GCM
- ✅ Keys stored in Android Keystore via EncryptedSharedPreferences
- ✅ API key masked in UI by default
- ✅ No logging of sensitive data
- ✅ TLS used for OpenAI connection (wss://)

## Potential Issues to Watch

### 1. EncryptedSharedPreferences Version
**Version used:** 1.1.0-alpha06

**Note:** This is an alpha version. Consider these points:
- Generally stable for production use
- Widely used in Android apps
- If issues arise, can fallback to 1.0.0 stable version

**Mitigation:** Test thoroughly; have rollback plan

### 2. API Key Validation
**Current state:** Basic null/blank check only

**TODO:** Add format validation
```kotlin
fun isValidApiKey(key: String): Boolean {
    return key.startsWith("sk-") && key.length > 20
}
```

### 3. Network Error Handling
**Current state:** Basic error logging + auto-reconnect

**TODO:** Add user-facing error notifications
- Show toast when API key is invalid
- Show notification when connection fails
- Add retry counter to prevent infinite loops

### 4. InCallService Priority
**Potential issue:** Multiple InCallService apps

**Mitigation:** User must set BandoPhone as default phone app
**TODO:** Add UI prompt to guide user through this setting

### 5. Audio Routing Edge Cases
**Watch for:**
- Bluetooth headset switching
- Wired headset plug/unplug during call
- Speaker phone toggle

**Current handling:** AudioManager MODE_IN_COMMUNICATION should handle this
**TODO:** Add explicit audio routing detection/logging

## Build-Time Checks Needed

When Java/Android Studio is available:

### Compilation
```bash
cd android
./gradlew clean
./gradlew assembleDebug
```

**Expected:** Clean build with no errors

**Watch for:**
- Import resolution issues
- API level compatibility warnings
- Deprecated API usage warnings

### Lint Checks
```bash
./gradlew lint
```

**Expected:** No critical issues

**Acceptable:** Warnings about experimental APIs (EncryptedSharedPreferences alpha)

### Unit Test Hooks
**TODO:** Add tests for:
- ApiKeyManager encryption/decryption
- Bridge connection logic
- Audio buffer management

## Runtime Testing Priority

### Phase 1: Settings UI
1. Install APK
2. Open app
3. Navigate to Settings
4. Enter test API key
5. Verify persistence
6. Try different voices
7. Edit instructions

**Pass criteria:** All settings save and reload correctly

### Phase 2: Permissions
1. Grant RECORD_AUDIO
2. Grant other requested permissions
3. Set as default phone app (Settings → Apps → Default apps → Phone app)

**Pass criteria:** All permissions granted, app is default phone handler

### Phase 3: Call Integration
1. Make outgoing call
2. Check logcat for BandoInCallService launch
3. Check for WebSocket connection
4. Check for audio streaming

**Pass criteria:** Service launches, connects to OpenAI

### Phase 4: Conversation
1. Speak to AI
2. Listen for response
3. Try interrupting AI mid-sentence
4. Test different phrases

**Pass criteria:** Natural conversation with working interruptions

### Phase 5: Edge Cases
1. Call during poor network
2. Call with invalid API key
3. Rapid call connect/disconnect
4. Background app during call

**Pass criteria:** Graceful degradation, no crashes

## Logcat Filters for Debugging

```bash
# All BandoPhone logs
adb logcat | grep -E "Bandophone|RealtimeAudio|CallAudio|BandoInCall"

# Just errors
adb logcat *:E | grep Bando

# WebSocket traffic
adb logcat | grep -i websocket

# Audio system
adb logcat | grep AudioTrack | grep AudioRecord
```

## Files to Monitor

### Source Files
- `CallAudioManager.kt` - Call lifecycle
- `RealtimeAudioBridge.kt` - WebSocket & audio
- `ApiKeyManager.kt` - Credentials
- `SettingsActivity.kt` - User config

### Generated Files
- `BuildConfig.java` - Build configuration
- `R.java` - Resources (should auto-generate)

### Configuration
- `AndroidManifest.xml` - Permissions & services
- `build.gradle` - Dependencies

## Rollback Plan

If critical issues are found:

### Quick Disable
1. Remove/comment out InCallService from manifest
2. Rebuild and redeploy
3. Fallback to external bridge mode

### Full Rollback
```bash
git log --oneline | head -5
git revert <integration-commit>
./gradlew assembleDebug
```

## Success Criteria

Integration is considered **successful** when:

1. ✅ App builds without errors
2. ✅ Settings UI works and persists data
3. ✅ BandoInCallService launches on calls
4. ✅ WebSocket connects to OpenAI
5. ✅ Audio streams bidirectionally
6. ✅ AI responds to user speech
7. ✅ Interruptions work naturally
8. ✅ Call end cleans up properly
9. ✅ No memory leaks
10. ✅ Battery usage reasonable

## Current Status

- ✅ Code written
- ✅ Manual review completed
- ⏳ Build verification pending (requires Java)
- ⏳ Runtime testing pending (requires device)
- ⏳ Edge case testing pending
- ⏳ User acceptance testing pending

## Next Immediate Actions

1. **Install Java 17 or Android Studio**
   ```bash
   # On macOS with Homebrew
   brew install openjdk@17
   ```

2. **Run build**
   ```bash
   cd ~/projects/bandophone/android
   export JAVA_HOME=$(/usr/libexec/java_home -v 17)
   ./gradlew assembleDebug
   ```

3. **Deploy to device**
   ```bash
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```

4. **Test and iterate**

## Additional Resources

- Architecture doc: `docs/NATIVE_AUDIO_ARCHITECTURE.md`
- Integration summary: `INTEGRATION_SUMMARY.md`
- This checklist: `VERIFICATION_CHECKLIST.md`
- Main README: `README.md`
