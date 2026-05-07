# ─── aria_voice.py ────────────────────────────────────────
# Aria's voice — Text to Speech.
#
# How it works:
#   pyttsx3 talks to Windows SAPI (built-in TTS engine).
#   We reinitialize the engine on every speak() call.
#   This is intentional — pyttsx3 has a known Windows bug
#   where runAndWait() breaks after the first call in a loop.
#   Reinitializing each time is the reliable fix.
#
# Later this file will be upgraded to VibeVoice Realtime-0.5B
# for much more natural, low-latency voice output.

import pyttsx3

# ─── SETTINGS ─────────────────────────────────────────────
VOICE_RATE   = 185   # speaking speed. default is ~200. lower = slower, higher = faster
VOICE_VOLUME = 1.0   # volume. 0.0 (silent) to 1.0 (max)

print("[voice]: TTS ready.")


# ─── SPEAK ────────────────────────────────────────────────
def speak(text: str):
    """
    Takes a string and speaks it out loud through your speakers.
    Reinitializes pyttsx3 engine every call — fixes Windows loop bug
    where the engine silently dies after the first runAndWait().
    """
    if not text or not text.strip():
        return

    try:
        # fresh engine every time — this is the fix
        tts = pyttsx3.init()

        # pick Zira (female voice)
        voices = tts.getProperty("voices")
        for voice in voices:
            if "zira" in voice.name.lower():
                tts.setProperty("voice", voice.id)
                break

        tts.setProperty("rate", VOICE_RATE)
        tts.setProperty("volume", VOICE_VOLUME)

        tts.say(text)
        tts.runAndWait()
        tts.stop()

    except Exception as e:
        print(f"[voice]: error — {e}")


# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    speak("Hey. You actually got me working. Don't make it weird.")
    speak("See? I can speak more than one line now.")
    speak("You're welcome.")