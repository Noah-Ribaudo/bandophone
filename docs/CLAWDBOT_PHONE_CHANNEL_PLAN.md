# Bandophone as Clawdbot Channel - Integration Plan

## Goal
Make phone calls a first-class Clawdbot channel while preserving OpenAI Realtime API features (server VAD, barging, sub-second latency).

## Current State
- Bandophone app on rooted Pixel 7 Pro
- TinyALSA captures far-end audio from phone calls
- Streams to OpenAI Realtime API for conversation
- Works standalone - no Clawdbot integration
- No access to tools, memories, or session context

## Design Principles
1. **Latency is king** - Voice conversations need <1s response time
2. **Realtime API features are essential** - Server VAD, barging, streaming
3. **Clawdbot context enriches conversations** - Memories, user info, recent activity
4. **Transcripts should be preserved** - Treat phone like any other channel
5. **Progressive enhancement** - Start simple, add features incrementally

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        PHONE CALL                                │
│  ┌──────────┐    ┌───────────────┐    ┌──────────────────────┐  │
│  │ Far-end  │───▶│  TinyALSA     │───▶│  OpenAI Realtime API │  │
│  │ (caller) │◀───│  Capture/Play │◀───│  (voice + function)  │  │
│  └──────────┘    └───────────────┘    └──────────┬───────────┘  │
└───────────────────────────────────────────────────┼──────────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────┐
                    │           CLAWDBOT GATEWAY    │               │
                    │  ┌────────────────────────────▼─────────────┐ │
                    │  │         Phone Channel Adapter            │ │
                    │  │  • Receives transcripts                  │ │
                    │  │  • Handles function call bridges         │ │
                    │  │  • Provides context injection            │ │
                    │  └────────────────────────────┬─────────────┘ │
                    │                               │               │
                    │  ┌────────────────────────────▼─────────────┐ │
                    │  │         Clawdbot Session                 │ │
                    │  │  • Tools (calendar, reminders, etc.)     │ │
                    │  │  • Memory (MEMORY.md, daily notes)       │ │
                    │  │  • Session history                       │ │
                    │  └──────────────────────────────────────────┘ │
                    └───────────────────────────────────────────────┘
```

---

## Phase 1: Context Injection (Day 1)

### What
On call start, fetch relevant context from Clawdbot and inject into Realtime API session instructions.

### Implementation

1. **Create context endpoint on Gateway** (or use existing session mechanism)
   ```
   GET /api/phone/context
   Response: {
     "user": { "name": "Noah", "timezone": "America/Chicago" },
     "memories": ["Recent: working on Bandophone project", ...],
     "calendar": ["Meeting at 3pm with...", ...],
     "recentActivity": ["Last message: ...", ...]
   }
   ```

2. **Phone app fetches context on call start**
   ```kotlin
   suspend fun fetchClawdbotContext(): PhoneContext {
       val response = httpClient.get("http://gateway:3000/api/phone/context")
       return response.body()
   }
   ```

3. **Inject into Realtime session instructions**
   ```kotlin
   val instructions = """
   You are Bando, Noah's AI assistant, taking a phone call.
   
   Current context:
   - User: ${context.user.name}
   - Time: ${LocalDateTime.now()} (${context.user.timezone})
   - Recent memories: ${context.memories.joinToString("\n")}
   - Today's calendar: ${context.calendar.joinToString("\n")}
   
   Be conversational, warm, and helpful. You have full context of Noah's life.
   If someone asks about appointments, projects, or recent activity, you know.
   """.trimIndent()
   ```

### Latency Impact
- One-time HTTP call at call start (~50-100ms)
- No impact on conversation latency

---

## Phase 2: Transcript Logging (Day 1-2)

### What
Stream transcripts to Clawdbot as the conversation happens, treating phone as a channel.

### Implementation

1. **WebSocket connection to Gateway**
   ```kotlin
   class ClawdbotBridge {
       private var ws: WebSocket? = null
       
       fun connect() {
           ws = OkHttpClient().newWebSocket(
               Request.Builder()
                   .url("ws://gateway:3000/api/phone/stream")
                   .build(),
               listener
           )
       }
       
       fun sendTranscript(speaker: String, text: String, isFinal: Boolean) {
           ws?.send(JsonObject().apply {
               addProperty("type", "transcript")
               addProperty("speaker", speaker)  // "user" or "assistant"
               addProperty("text", text)
               addProperty("final", isFinal)
               addProperty("timestamp", System.currentTimeMillis())
           }.toString())
       }
   }
   ```

2. **Gateway receives and logs**
   - Creates/updates phone session in session store
   - Appends to daily memory file: `memory/YYYY-MM-DD.md`
   - Format similar to other channels:
     ```markdown
     ## Phone Call (16:30 - 16:35)
     **Caller:** +1 555-1234
     
     User: Hey, what's on my calendar today?
     Bando: You have a meeting at 3pm with the design team...
     User: Can you remind me 15 minutes before?
     Bando: Done! I'll ping you at 2:45.
     ```

3. **Phone app hooks into Realtime events**
   ```kotlin
   // In HybridRealtimeBridge
   onTranscript = { text, isFinal ->
       clawdbotBridge.sendTranscript("assistant", text, isFinal)
   }
   
   // For user speech (from input_audio_transcription events)
   "conversation.item.input_audio_transcription.completed" -> {
       val text = event.optString("transcript")
       clawdbotBridge.sendTranscript("user", text, true)
   }
   ```

### Latency Impact
- Async WebSocket send - no blocking
- Zero impact on conversation

---

## Phase 3: Function Calling Bridge (Day 2-3)

### What
Enable Realtime API to call Clawdbot tools (calendar, reminders, lights, etc.)

### How Realtime API Function Calling Works
```json
// Define tools in session config
{
  "type": "session.update",
  "session": {
    "tools": [
      {
        "type": "function",
        "name": "get_calendar",
        "description": "Get calendar events for a date range",
        "parameters": {
          "type": "object",
          "properties": {
            "start_date": { "type": "string" },
            "end_date": { "type": "string" }
          }
        }
      },
      {
        "type": "function",
        "name": "create_reminder",
        "description": "Create a reminder",
        "parameters": {
          "type": "object",
          "properties": {
            "text": { "type": "string" },
            "time": { "type": "string" }
          }
        }
      }
    ]
  }
}
```

### Implementation

1. **Define bridged tools**
   ```kotlin
   val PHONE_TOOLS = listOf(
       Tool("get_calendar", "Get calendar events", mapOf(
           "start_date" to "string",
           "end_date" to "string"
       )),
       Tool("create_reminder", "Create a reminder", mapOf(
           "text" to "string", 
           "time" to "string"
       )),
       Tool("get_weather", "Get weather forecast", mapOf(
           "location" to "string"
       )),
       Tool("control_lights", "Control smart home lights", mapOf(
           "action" to "string",  // on/off/dim
           "room" to "string"
       ))
   )
   ```

2. **Handle function calls from Realtime API**
   ```kotlin
   "response.function_call_arguments.done" -> {
       val name = event.optString("name")
       val args = event.optString("arguments")
       
       // Bridge to Clawdbot
       scope.launch {
           val result = clawdbotBridge.callTool(name, args)
           
           // Send result back to Realtime API
           sendFunctionResult(event.optString("call_id"), result)
       }
   }
   ```

3. **Gateway tool execution endpoint**
   ```
   POST /api/phone/tool
   {
     "name": "get_calendar",
     "arguments": { "start_date": "2024-01-26", "end_date": "2024-01-26" }
   }
   
   Response:
   {
     "result": "You have 2 events today:\n- 3pm: Design team meeting\n- 6pm: Dinner with Jess"
   }
   ```

4. **Gateway executes via existing tool infrastructure**
   - Reuse Clawdbot's tool execution layer
   - Same tools available as in chat sessions
   - Results formatted for voice (concise, speakable)

### Latency Impact
- Tool calls add ~200-500ms (network + execution)
- But conversation continues - Realtime API handles waiting gracefully
- AI can say "Let me check that..." while tool executes

---

## Phase 4: Full Channel Integration (Day 3-4)

### What
Make phone a proper Clawdbot channel plugin, appearing in session lists, supporting cross-session features.

### Implementation

1. **Channel plugin structure**
   ```
   channels/phone/
   ├── index.ts          # Channel registration
   ├── adapter.ts        # WebSocket handler
   ├── context.ts        # Context injection
   └── tools.ts          # Tool definitions
   ```

2. **Session management**
   - Each call creates a phone session
   - Session key: `phone:+1234567890:timestamp`
   - Appears in `sessions_list` output
   - Can be referenced by other sessions

3. **Cross-session features**
   - Main session can check phone call status
   - "Bando, call Noah and remind him about the meeting"
   - Phone session can notify main session of important events

### Gateway Config
```yaml
channels:
  phone:
    enabled: true
    gatewayUrl: "ws://localhost:3000/api/phone/stream"
    contextEndpoint: "/api/phone/context"
    toolEndpoint: "/api/phone/tool"
    logTranscripts: true
    memoryPath: "memory/"
```

---

## Alternative: Simpler HTTP-Based Approach

If WebSocket complexity is too high initially:

1. **Poll-based context** (on call start)
2. **Batch transcript upload** (on call end)
3. **Synchronous tool calls** (HTTP POST, block briefly)

Less real-time but simpler to implement.

---

## Key Technical Decisions

### 1. Where does the Realtime API session live?
**On the phone.** Gateway is only for context/tools/logging.

### 2. How do we handle network issues?
- Buffer transcripts locally if connection drops
- Retry tool calls with timeout
- Graceful degradation - conversation continues even if gateway offline

### 3. How do we identify callers?
- Caller ID from Android telephony
- Lookup in contacts/directory
- Unknown callers get generic context

### 4. Security considerations
- Phone app authenticates to gateway (token in config)
- Tools have permission scoping (phone can't send emails, etc.)
- Transcripts are private (stored locally on gateway)

---

## Implementation Order

1. ✅ Basic phone call with Realtime API (DONE)
2. ⬜ Context injection from gateway
3. ⬜ Transcript logging to gateway
4. ⬜ Basic function calling (calendar, reminders)
5. ⬜ Full channel plugin
6. ⬜ Cross-session features

---

## Open Questions

1. Should phone use the main Clawdbot session or a separate phone session?
2. How much context is too much? (token limits in Realtime API)
3. Which tools make sense for voice? (some are too complex)
4. How to handle long-running tool calls? (AI should acknowledge)
5. Should we support incoming calls differently than outgoing?

---

## Success Metrics

- Context injection: <100ms added latency at call start
- Transcripts logged within 1s of speech
- Tool calls complete within 500ms (simple) to 2s (complex)
- Full conversation preserved in memory
- Phone sessions visible in Clawdbot status
