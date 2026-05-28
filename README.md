# EasyQuestionPicker

`EasyQuestionPicker` is a Windows desktop helper for viewing and claiming questions from the Xunfei pool 1 page.

It combines:

- a Tkinter desktop UI
- an optional built-in WebView browser for login
- a Playwright CDP connection for reading live pool data and claiming questions
- a lightweight in-memory session cache to reduce repeated processing during refreshes

The current workflow is focused on:

- `https://static.xunfeixxj.com/videoMachiningPlatform/#/claim/pools/1`

## What It Does

- Open a built-in browser window and keep the logged-in session
- Or connect to an external Chrome / Edge debugging session
- Fetch the current available questions from pool 1 directly from the live page logic
- Preview question text and images inside the desktop app
- Claim the selected question inside the desktop app
- Highlight newly appeared questions after a refresh
- Keep a small session-only cache so repeated refreshes feel faster

## Current UI Actions

Top toolbar buttons:

- `Built-in`: start the built-in WebView browser
- `Browser`: launch an external Chrome / Edge debugging browser
- `Refresh`: fetch the latest live questions from pool 1
- `Claim`: claim the selected question
- `Inspect`: inspect the current browser tab and page state
- `Import`: load a saved local JSON file
- `Settings`: edit browser and runtime options

## Recommended Workflow

1. Start the app.
2. Click `Built-in`.
3. Log in with your internal account in the built-in browser.
4. Go to the pool 1 page if it is not already there.
5. Return to the app and click `Refresh`.
6. Select a question from the left list.
7. Preview it on the right side.
8. Click `Claim` to claim it directly in the app.

If you prefer an external browser session, use `Browser` instead of `Built-in`.

## Built-in Browser Notes

The built-in browser uses `pywebview` with Edge Chromium and keeps its own profile directory.

Current behavior:

- text selection is enabled
- external links can still open in the system browser
- the internal preview masking CSS / JS is bypassed in the embedded WebView

This project is Windows-focused and expects WebView2 / Edge Chromium support on the machine.

## Cache Behavior

The app already includes a lightweight session cache.

How it works:

- When live questions are fetched, the app builds a small in-memory cache for the current session.
- If a question is still present and its signature has not changed, the app reuses the cached processed result.
- If a question disappears, it drops out of the next cache snapshot automatically.
- After a successful claim, the app refreshes pool 1 again, so the claimed question is removed and newly available questions can appear.
- The cache is intentionally small and session-scoped.
- Closing the app clears the session cache.
- Local temporary preview data in `captured/` is also cleared on startup / shutdown through the runtime reset flow.

This matches the intended behavior of:

- old item disappears after it is claimed or removed
- new item can join on the next refresh
- no large persistent disk cache is kept

## Project Structure

```text
EasyWorking/
|- app.py
|- build_exe.ps1
|- requirements.txt
|- question_viewer/
|  |- browser_capture.py
|  |- capture_config.py
|  |- loader.py
|  |- models.py
|  |- paths.py
|  |- ui.py
|  `- webview_host.py
`- vendor/
```

## Main Files

- [app.py](/E:/PythonProjects/EasyWorking/app.py): entry point
- [question_viewer/ui.py](/E:/PythonProjects/EasyWorking/question_viewer/ui.py): desktop UI
- [question_viewer/browser_capture.py](/E:/PythonProjects/EasyWorking/question_viewer/browser_capture.py): browser connection, live fetch, claim logic, cache logic
- [question_viewer/webview_host.py](/E:/PythonProjects/EasyWorking/question_viewer/webview_host.py): built-in WebView host
- [question_viewer/capture_config.py](/E:/PythonProjects/EasyWorking/question_viewer/capture_config.py): runtime config model and persistence
- [build_exe.ps1](/E:/PythonProjects/EasyWorking/build_exe.ps1): Windows packaging script

## Requirements

- Windows
- Python 3.10+ recommended
- Chrome or Edge available on the machine
- Edge WebView2 runtime available for built-in browser mode

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python app.py
```

## Build EXE

```powershell
.\build_exe.ps1
```

After build:

```text
dist\EasyQuestionPicker.exe
```

## Runtime Data

The app may create local runtime files such as:

- `capture_config.json`
- `captured/latest_questions.json`
- `captured/assets/...`
- `.browser_profile/`
- `.webview_profile/`
- `.runtime/`

These are local machine artifacts and are already covered by `.gitignore`.

## Git Notes

The repository includes a `.gitignore` that ignores:

- Python cache files
- virtual environments
- IDE settings
- build output
- local browser / WebView profiles
- local runtime capture data
- temporary packaged artifacts

## Known Scope

This project currently targets pool 1 only.

It is not designed as a generic scraper for every platform page. The current implementation is intentionally tailored to the existing Xunfei pool 1 workflow and the current internal page structure.
