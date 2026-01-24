# Audio Routing Research

Device-specific findings for call audio capture.

## Pixel 7 Pro (Tensor G2)

**Status**: 🔬 Under Investigation

### PCM Devices Found

```
# From /proc/asound/pcm (needs verification during active call)
```

*TODO: Run diagnostics during active call*

### Mixer Controls

```
# From tinymix output
```

*TODO: Identify relevant controls*

### Sample Rates

- GSM: 8000 Hz
- VoLTE (AMR-WB): 16000 Hz  
- VoLTE (EVS): 32000 Hz

*TODO: Confirm which codec T-Mobile uses*

### Notes

- SELinux must be permissive
- Audio HAL: 
- Modem: Samsung Shannon

---

## Adding Your Device

1. Run `./scripts/diagnose.sh` during an active call
2. Capture the output
3. Open a PR adding your device section

Template:
```markdown
## [Device Name] ([SoC])

**Status**: 🔬 Under Investigation | ✅ Working | ❌ Not Working

### PCM Devices Found
[paste from diagnose.sh]

### Mixer Controls  
[relevant tinymix output]

### Sample Rates
[observed rates]

### Notes
[any quirks or requirements]
```
