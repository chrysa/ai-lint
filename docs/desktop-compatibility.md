# Desktop portability observations

Normal scans now detect selected desktop application shapes without installing
frameworks or executing application commands. Detected projects have profile
`desktop-app` and a `desktop` section with frameworks and evidence.

The first increment recognizes Electron and Tauri package dependencies, Tauri JSON
metadata, and PySide/PyQt, Tkinter, wxPython and Kivy references in common Python
metadata/entrypoints. This is heuristic detection at medium confidence; comments,
optional dependencies and unused imports can produce evidence too.

JSON includes `desktop_compatibility` with per-project detection, framework
signals, packaging metadata and per-OS observations. Findings use category
`desktop` and are advisory, manual-only observations. TUI readiness shows the same
Linux/macOS/Windows runner signals. `runtime_verified` is always false.

- `DESKTOP_PATH_ASSUMPTION`: a selected file mentions a platform-specific path.
  Review platform branches and portable configuration handling before changing it.
- `DESKTOP_LAUNCH_ASSUMPTION`: a package script uses POSIX tools/environment syntax
  or a platform-specific shell launcher. Check the launcher on each intended OS.
- `DESKTOP_CI_UNOBSERVED`: no literal Ubuntu/macOS/Windows hosted runner label was
  observed in sampled GitHub workflows. Dynamic matrices, self-hosted runners,
  external CI and intentionally single-OS projects may be valid.
- `DESKTOP_PACKAGING_UNOBSERVED`: no sampled packaging metadata was observed.
  Confirm the distribution plan; this does not establish that packaging is absent.

The bounded scan reads selected root metadata, `main.py`, `app.py`, their `src/`
variants, up to 20 workflow files, and root packaging hints. Files larger than
256 KB and symlinked paths are skipped. Literal CI labels may appear in comments;
commands are listed by script name without proving they run on a particular OS.
The checker does not parse workflow execution semantics or test the build.

Native/.NET/Java wrappers, deep source analysis, configured application data paths,
additional framework layouts, full packaging target analysis and OS test execution
remain follow-ups in issue #26. Existing agent configuration paths and public
wrappers retain their behavior. No critical project content is modified.
