# PMM4RPAAI Activity Ranking

Load your process data, set one or two improvement goals, and see which activities
would contribute most to those goals if they were automated. The shortlist is the set
of top-ranked activities that reaches your targets. Shortlisted activities can then be
assessed task by task with a questionnaire.

Built for the uOttawa Process Mining lab's PMM4RPAAI methodology
(`ProcessMining-uOttawa/PMM4RPAAI`). The computations are in Python; the page is a
plain HTML/JavaScript front end served by the same app.

## Run

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in a browser. Data stays on your computer: the app runs
locally and keeps it in memory only.

The page loads its font from Google Fonts, so it looks slightly different offline.

## Use

1. **Process data.** Choose one of:
   - **Event log**: a CSV with one row per activity execution. Columns are matched
     automatically and can be re-mapped on the page: case ID, activity, start time and
     end time (or a duration in minutes), and optionally a cost column and/or an hourly
     cost rate column. "Use sample log" loads an invented log to try the app.
   - **Activity table**: a CSV with one row per activity and its totals
     (`activity, total_duration, total_cost, rework_duration`), e.g. the lab's
     `activity_data.csv`. Pick the unit its durations are in.
   - **Enter by hand**: the total processing time of the process and each activity's
     time, in minutes.
2. **Goals.** Choose one or two of processing time, cost and rework time, and set a
   target reduction (%) for each.
3. **Ranked activities.** Activities are ranked and the top ones are shortlisted until
   every target is reached. "Export ranking (CSV)" saves the table.
4. **Assess the shortlisted activities.** Split each shortlisted activity into tasks
   and score them on six criteria to get automation feasibility, bot failure rate, bot
   time and number of bots, with optimistic / likely / pessimistic estimates. The
   result can be downloaded as simulation inputs for PMM4RPAAI-Sim.

## How the numbers are calculated

All times are in minutes.

- **Processing time** of an execution is end time minus start time, or the duration
  column. Waiting time between activities is not counted.
- **Cost** of an execution is the value of the cost column where it has one. Otherwise
  it is processing time × the hourly rate: the rate column, or the default rate for
  rows without a rate.
- **Rework time** is the processing time of the second and later executions of the
  same activity within a case.
- Each activity is assumed to be 100% automated, so its estimated reduction for a goal
  equals its share of that goal's total.
- **One goal:** activities are ranked by their share and shortlisted from the top until
  the cumulative share reaches the target.
- **Two goals:** both count equally. Activities are ranked by a combined score, the
  average of their two shares, and shortlisted from the top until both targets are
  reached. There is one shortlist for both goals.
- Activities that contribute nothing to the selected goals are left out of the ranking;
  those with zero recorded time are treated as already automated.
- With data entered by hand, shares are taken from the total processing time you
  entered, which can exceed the sum of the activity times because of waiting.
- Rows whose case, activity or time cannot be read are skipped, and the page reports
  how many.

## Project layout

- `app.py`: Flask entry point
- `pmm4rpaai/eventlog/parser.py`: event log CSV -> normalized rows (column mapping, cost)
- `pmm4rpaai/eventlog/mining.py`: normalized rows -> per-activity metrics
- `pmm4rpaai/eventlog/aggregated.py`: activity table CSV -> per-activity metrics
- `pmm4rpaai/ranking/engine.py`: single-goal ranking and the combined ranking/shortlist
- `pmm4rpaai/assessment/feasibility.py`: task questionnaire scoring
- `pmm4rpaai/api/routes.py`: endpoints (`/api/preview`, `/api/upload`,
  `/api/upload-activities`, `/api/manual-activities`, `/api/rank`, `/api/assess`,
  `/api/export/<upload_id>`, `/api/sim-factors/<upload_id>`)
- `static/`: the page (HTML, CSS, JavaScript; no build step) and the sample log
- `tests/`: parser, mining, ranking and assessment tests, including a check against
  the lab's own `activity_data.csv` and a characterization test of the single-goal
  ranking against previously generated output

## Tests

```
python -m pytest tests -q
```
