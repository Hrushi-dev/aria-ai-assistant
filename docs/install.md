# Software Installation & Fix Checklist

This is a reminder of the software and fixes you need to apply to get your AI assistant running smoothly again.

## 1. Fix Anaconda & Python Environments (CRITICAL)
Your virtual environments are broken because the base Python path changed.
* **The Problem**: You accidentally moved your Anaconda folder. It used to be at `D:\anaconda_stuff`, but it is currently sitting at `D:\d_vol\anaconda_stuff`.
* **The Fix**: Simply move the `anaconda_stuff` folder back to the root of the `D:\` drive so it sits at `D:\anaconda_stuff`. Once you do this, your `venv` should magically start working again without needing to reinstall anything!

## 2. Install espeak-ng
* **Why**: Required by Kokoro-ONNX for text-to-speech phonemization on Windows.
* **Action**: Download and install from [espeak-ng releases](https://github.com/espeak-ng/espeak-ng/releases). Ensure it gets added to your system PATH during installation.

## 3. Install NirCmd
* **Why**: Used in `aria-voice/commands.py` for muting and changing system volume.
* **Action**: Download [NirCmd](https://www.nirsoft.net/utils/nircmd.html). Extract `nircmd.exe` into this project folder (`d:\d_vol\AI-AIS`) or place it somewhere in your Windows PATH.

## 4. Run Docker Desktop
* **Why**: Required by `start_aria.bat` to launch the `aria-tg-api` container for Telegram control.
* **Action**: Make sure you open the Docker Desktop application and wait for the daemon to start running before you run the background daemon.
