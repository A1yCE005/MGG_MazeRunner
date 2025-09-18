# MGG MazeRunner

MGG MazeRunner is a desktop automation assistant for the Maze Runner event in Muv-Luv: Girls Garden X. It provides a PySide6 control panel around the `MazeBot` template-matching engine so you can monitor logs, tweak thresholds, and launch or stop the automation with one click.

## Features
- Fluent UI built with PySide6 Fluent Widgets
- Template-based computer-vision routing with OpenCV and MSS screen capture
- Configurable detection thresholds, event priorities, and hotkeys
- Built-in logging panel with export support and optional low-power timings

## Requirements
- Windows 10/11 with Python 3.9+ available as `py` or `python`
- Game window running in windowed mode with the expected title (defaults come from `config.json`)
- Screen scale set so templates in `templates/` match the game assets

## Getting Started
1. Double-click `run.bat` (or run it from a terminal). The script creates a virtual environment, installs dependencies from `requirements.txt`, and launches the UI.
2. If you prefer manual setup:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python bot_fluent.py
   ```

## Usage
- Use the **Window Title** field or the window picker to bind the bot to the correct game window.
- Adjust thresholds, sleep timings, route ratio, and event priority on the **Control** and **Settings** tabs.
- Start (`F4`) and stop (`F3`) the bot with the default hotkeys (editable in the UI).
- Watch the live log; click **Export Log...** to save a timestamped text file for debugging.

## Configuration & Templates
- Runtime settings are persisted in `config.json` automatically. You can edit the file by hand, but the UI keeps it up to date.
- Vision templates live under `templates/`. Replace or add PNGs to extend detection coverage; filenames become template keys.

## Troubleshooting
- If the bot cannot find the game window, confirm the title matches and that the client is visible on the primary monitor.
- Large DPI scaling can throw off template matches. The provided Qt DPI variables in `run.bat` help, but you may still need to adjust Windows scaling or capture new templates.
- For stuck states, enable **Debug Mode** to capture additional log context and re-run the scenario.

