# Example output

`demo-report/` is a real, unedited run of the bundled demo tour
(`demo/tour.py` against `demo/app.py`), committed so you can see what a
walkthrough produces without running anything:

- `report.html` - open it in a browser (media is linked, so keep the
  directory together; use `ccwalk report demo-report --embed` to produce
  a single self-contained file)
- `report.md` - the agent/diff-friendly twin
- `run_meta.json` - the machine-readable per-step results
- `screenshots/` - note `005..009_analyze_note_wait_*.png`: the slow
  async operation captured mid-progress by `wait_for_condition`
- `videos/` - one .webm per step group (login, notes, analysis, mobile)

Regenerate it any time:

```bash
CCWALK_DEMO_USER=demo CCWALK_DEMO_PASS=demo123 \
  uv run ccwalk run --config demo/ccwalk.yaml --start-app
```
