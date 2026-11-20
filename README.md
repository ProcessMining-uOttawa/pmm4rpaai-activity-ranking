# PMM4RPAAI Activity Ranking

Load a process event log, set one or two improvement goals, and see which activities
would contribute most to those goals if they were automated. The shortlist is the set
of top-ranked activities that reaches your targets.

The app is a single HTML page. It runs entirely in the browser: the event log is read
locally and is not uploaded anywhere.

## Run

Open `index.html` in a browser. No installation or build step is needed.

An internet connection is required the first time, because the page loads its CSV
reader (PapaParse) and its font from public CDNs.

## Use

1. **Event log.** Load a CSV file with one row per activity execution, or click
   "Use sample log" to try it with invented data. The columns are matched
   automatically and can be re-mapped:
   - case ID
   - activity name
   - start time and end time, or a duration in minutes
   - hourly cost rate (optional; otherwise the default rate you enter is used)
2. **Goals.** Choose one or two of processing time, cost and rework time, and set a
   target reduction (%) for each.
3. **Ranked activities.** Activities are ranked by their share of the total. The top
   ones are shortlisted until every target is reached. "Export ranking (CSV)" saves
   the table.

## How the numbers are calculated

- **Processing time** of an execution is end time minus start time (or the duration
  column). Waiting time between activities is not counted.
- **Cost** is processing time multiplied by the hourly rate.
- **Rework time** is the processing time of the second and later executions of the
  same activity within a case.
- Each activity is assumed to be 100% automated, so its estimated reduction equals its
  share of the total.
- With two goals, both count equally: activities are ranked by the average of their
  two estimated reductions.
- Activities with zero recorded duration are treated as already automated and are left
  out of the ranking.
- Rows whose case, activity or time cannot be read are skipped, and the page reports
  how many.
