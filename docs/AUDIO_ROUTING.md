# Audio Routing Research

Device-specific findings for call audio capture.

## Pixel 7 Pro (Tensor G2)

**Status**: 🔬 Discovery Complete — Ready for Call Testing

### Hardware
- **SoC**: Google Tensor G2
- **Sound Card**: `google,aoc-snd-card` (AOC = Always-On Co-processor)
- **Modem**: Samsung Shannon (VoLTE capable)
- **Android**: 16

### PCM Devices for Calls

| Device | Name | Direction | Purpose |
|--------|------|-----------|---------|
| pcmC0D18p | audio_incall_pb_0 | Playback | Inject audio into call |
| pcmC0D19p | audio_incall_pb_1 | Playback | Secondary playback |
| pcmC0D29p | audio_incall_pb_2 | Playback | Tertiary playback |
| pcmC0D20c | audio_incall_cap_0 | Capture | Capture call audio |
| pcmC0D21c | audio_incall_cap_1 | Capture | Secondary capture |
| pcmC0D22c | audio_incall_cap_2 | Capture | Tertiary capture |

### Audio Format (from tinypcminfo)

**Capture Device (pcmC0D20c):**
- Formats: S16_LE, S24_LE, S32_LE
- Sample rates: 8000 - 48000 Hz
- Channels: 1 - 8

**Playback Device (pcmC0D18p):**
- Formats: S16_LE, S24_LE, S32_LE, S24_3LE
- Sample rates: 8000 - 48000 Hz
- Channels: 1 - 2

### Critical Mixer Controls

**Voice Call Controls:**
| ID | Name | Values | Current |
|----|------|--------|---------|
| 148 | Voice Call Mic Source | Default, Builtin_MIC, USB_MIC, BT_MIC, IN_CALL_MUSIC | Builtin_MIC |
| 149 | Voice Call Mic Mute | Off/On | Off |
| 150 | Voice Call Audio Enable | Off/On | On |
| 188 | Voice Call Rx Volume | 0-100 | -1 |

**Incall Capture Controls (THE KEY ONES):**
| ID | Name | Values | Meaning |
|----|------|--------|---------|
| 152 | Incall Capture Stream0 | Off, UL, DL, UL_DL, 3MIC | Stream 0 routing |
| 153 | Incall Capture Stream1 | Off, UL, DL, UL_DL, 3MIC | Stream 1 routing |
| 154 | Incall Capture Stream2 | Off, UL, DL, UL_DL, 3MIC | Stream 2 routing |
| 155 | Incall Capture Stream3 | Off, UL, DL, UL_DL, 3MIC | Stream 3 routing |

**Values explained:**
- `Off` — Stream disabled
- `UL` — Uplink only (what YOU say into the mic)
- `DL` — Downlink only (what the OTHER PARTY says)
- `UL_DL` — Both sides mixed together
- `3MIC` — Three microphone input (noise cancellation?)

**Incall Playback Controls:**
| ID | Name | Values |
|----|------|--------|
| 156 | Incall Playback Stream0 | Off/On |
| 157 | Incall Playback Stream1 | Off/On |
| 167 | Incall Mic Mute | Off/On |
| 168 | Incall Sink Mute | Off/On |
| 169 | Incall Mic Gain (dB) | -300 to 30 |

### Expected Call Flow

To capture both sides of a call:
1. Set `Incall Capture Stream0` to `UL_DL`
2. Open `pcmC0D20c` for capture
3. Read S16_LE data at 16000Hz (VoLTE standard)

To inject audio (AI responses) into a call:
1. Set `Incall Playback Stream0` to `On`
2. Open `pcmC0D18p` for playback
3. Write S16_LE data at 16000Hz

### Test Commands

```bash
# Set capture to mixed uplink+downlink
tinymix set "Incall Capture Stream0" "UL_DL"

# Capture 5 seconds during active call
tinycap /data/local/tmp/call.wav -D 0 -d 20 -c 1 -r 16000 -b 16 -T 5

# Play audio into call
tinyplay /data/local/tmp/response.wav -D 0 -d 18 -c 1 -r 16000 -b 16
```

### Notes

- Devices may only be accessible during an active call
- SELinux must be permissive: `setenforce 0`
- VoLTE (T-Mobile) likely uses 16000Hz AMR-WB
- Audio HAL may need the call to be in "voice call" mode (check `Audio DSP State`)

### TODO
- [ ] Verify capture works during active call
- [ ] Determine exact sample rate for VoLTE
- [ ] Test audio injection doesn't disrupt call
- [ ] Check if separate UL/DL streams are more reliable than UL_DL

---

## Adding Your Device

1. Run `./scripts/diagnose.sh` during an active call
2. Search mixer output for `incall`, `voice`, `call`, `modem`
3. Find PCM devices with similar names
4. Document mixer control IDs and PCM device numbers
5. Open a PR!
