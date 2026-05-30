"""
Garmin Connect data explorer.
Saves session tokens to .garmin_tokens/ — subsequent runs skip login.
"""

from datetime import date, timedelta
from getpass import getpass
from pathlib import Path

from garminconnect import Garmin

TOKEN_DIR = str(Path(__file__).parent / ".garmin_tokens")


def get_client() -> Garmin:
    token_path = Path(TOKEN_DIR)
    if token_path.exists() and any(token_path.iterdir()):
        client = Garmin()
        client.login(TOKEN_DIR)
        print("Logged in from saved session.")
        return client

    email = input("Garmin email: ")
    password = getpass("Garmin password: ")
    client = Garmin(email=email, password=password)
    client.login(TOKEN_DIR)
    print("Session saved.")
    return client


def show_stats(client: Garmin, today: date):
    print("\n--- Today's stats ---")
    stats = client.get_stats(today.isoformat())
    steps = stats.get("totalSteps", 0)
    goal = stats.get("dailyStepGoal", 0)
    dist_km = stats.get("totalDistanceMeters", 0) / 1000
    print(f"  Steps:            {steps:,} / {goal:,}")
    print(f"  Distance:         {dist_km:.1f} km")
    print(f"  Total kcal:       {stats.get('totalKilocalories', 'n/a'):.0f}")
    print(f"  Active kcal:      {stats.get('activeKilocalories', 'n/a'):.0f}")
    active_min = stats.get("activeSeconds", 0) // 60
    print(f"  Active time:      {active_min} min")

    hr = client.get_heart_rates(today.isoformat())
    print(f"  Resting HR:       {hr.get('restingHeartRate', 'n/a')} bpm")


def _dedup_activities(activities: list) -> list:
    """One entry per (date, distance_rounded).

    When duplicates exist, prefer road_biking > cycling so we keep power data.
    """
    TYPE_PREF = {"road_biking": 0, "cycling": 1}

    buckets: dict[tuple, list] = {}
    for a in activities:
        day = a.get("startTimeLocal", "")[:10]
        dist = round(a.get("distance", 0) / 2000) * 2  # bucket to nearest 2 km
        key = (day, dist)
        buckets.setdefault(key, []).append(a)

    out = []
    for key in buckets:
        candidates = buckets[key]
        best = min(
            candidates,
            key=lambda a: TYPE_PREF.get(
                a.get("activityType", {}).get("typeKey", ""), 99
            ),
        )
        out.append(best)

    out.sort(key=lambda a: a.get("startTimeLocal", ""), reverse=True)
    return out


def show_activities(client: Garmin, limit: int = 10):
    raw = client.get_activities(0, limit * 2)  # fetch extra to allow for dupes
    activities = _dedup_activities(raw)[:limit]
    print(f"\n--- Last {len(activities)} activities (de-duplicated) ---")
    for a in activities:
        atype = a.get("activityType", {}).get("typeKey", "?")
        name = a.get("activityName", "")
        dist = round(a.get("distance", 0) / 1000, 2)
        dur = int(a.get("duration", 0) // 60)
        avg_hr = a.get("averageHR", "n/a")
        avg_power = a.get("avgPower")
        power_str = f"  {avg_power:.0f}W" if avg_power else ""
        print(
            f"  {a.get('startTimeLocal', '')[:10]}  "
            f"{atype:20s}  {name[:35]:35s}  "
            f"{dist:6.1f} km  {dur:4d} min  HR {avg_hr}{power_str}"
        )


def show_activity_detail(client: Garmin, activity_id: str):
    print(f"\n--- Activity detail: {activity_id} ---")
    detail = client.get_activity(activity_id)
    summary = detail.get("summaryDTO", {})
    print(f"  Avg HR:           {summary.get('averageHR', 'n/a')} bpm")
    print(f"  Max HR:           {summary.get('maxHR', 'n/a')} bpm")
    print(f"  Avg power:        {summary.get('avgPower', 'n/a')} W")
    print(f"  Max power:        {summary.get('maxPower', 'n/a')} W")
    print(f"  Avg cadence:      {summary.get('averageBikingCadenceInRevPerMinute', summary.get('averageRunningCadenceInStepsPerMinute', 'n/a'))}")
    print(f"  Elevation gain:   {summary.get('elevationGain', 'n/a')} m")
    print(f"  Calories:         {summary.get('calories', 'n/a')}")
    print(f"  Training effect:  aerobic={summary.get('aerobicTrainingEffect', 'n/a')}  anaerobic={summary.get('anaerobicTrainingEffect', 'n/a')}")

    hr_zones = client.get_activity_hr_in_timezones(activity_id)
    if hr_zones:
        print("  HR zones:")
        for z in hr_zones:
            secs = z.get("secsInZone", 0)
            print(f"    Zone {z.get('zoneNumber', '?')}: {secs // 60} min")

    power_zones = client.get_activity_power_in_timezones(activity_id)
    if power_zones:
        print("  Power zones:")
        for z in power_zones:
            secs = z.get("secsInZone", 0)
            print(f"    Zone {z.get('zoneNumber', '?')}: {secs // 60} min")


def show_sleep(client: Garmin, today: date):
    print("\n--- Last night's sleep ---")
    sleep = client.get_sleep_data(today.isoformat())
    daily = sleep.get("dailySleepDTO", {})
    score = daily.get("sleepScores", {}).get("overall", {}).get("value", "n/a")
    total_h = daily.get("sleepTimeSeconds", 0) / 3600
    deep_min = daily.get("deepSleepSeconds", 0) // 60
    rem_min = daily.get("remSleepSeconds", 0) // 60
    light_min = daily.get("lightSleepSeconds", 0) // 60
    awake_min = daily.get("awakeSleepSeconds", 0) // 60
    avg_spo2 = daily.get("averageSpO2Value", "n/a")
    avg_rhr = daily.get("averageRestingHeartRate", "n/a")
    avg_stress = daily.get("averageStressLevel", "n/a")
    print(f"  Sleep score:      {score}")
    print(f"  Total sleep:      {total_h:.1f} h")
    print(f"  Deep:             {deep_min} min")
    print(f"  REM:              {rem_min} min")
    print(f"  Light:            {light_min} min")
    print(f"  Awake:            {awake_min} min")
    print(f"  Avg resting HR:   {avg_rhr} bpm")
    print(f"  Avg SpO2:         {avg_spo2}%")
    print(f"  Avg stress:       {avg_stress}")


def show_hrv(client: Garmin, today: date):
    print("\n--- HRV (last 7 days) ---")
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        data = client.get_hrv_data(d)
        if not data:
            continue
        summary = data.get("hrvSummary", {})
        if not summary:
            continue
        last_night = summary.get("lastNightAvg", "n/a")
        last_night_high = summary.get("lastNight5MinHigh", "n/a")
        weekly_avg = summary.get("weeklyAvg", "n/a")
        status = summary.get("status", "")
        baseline = summary.get("baseline", {})
        bal_low = baseline.get("balancedLow", "n/a")
        bal_high = baseline.get("balancedUpper", "n/a")
        print(
            f"  {d}: last night avg={last_night}  5min high={last_night_high}"
            f"  weekly avg={weekly_avg}  baseline={bal_low}-{bal_high}  status={status}"
        )


def show_weekly_trends(client: Garmin, today: date, weeks: int = 4):
    print(f"\n--- Weekly trends (last {weeks} weeks) ---")
    for w in range(weeks - 1, -1, -1):
        week_start = today - timedelta(days=today.weekday() + w * 7)
        week_end = week_start + timedelta(days=6)
        acts = _dedup_activities(
            client.get_activities_by_date(week_start.isoformat(), week_end.isoformat())
        )
        rides = [a for a in acts if "cycling" in a.get("activityType", {}).get("typeKey", "").lower()
                 or "biking" in a.get("activityType", {}).get("typeKey", "").lower()]
        total_km = sum(a.get("distance", 0) for a in rides) / 1000
        total_min = sum(a.get("duration", 0) for a in rides) / 60
        print(f"  {week_start}:  {len(rides)} rides  {total_km:.0f} km  {total_min:.0f} min")


def show_body_battery(client: Garmin, today: date):
    print("\n--- Body Battery (today) ---")
    data = client.get_body_battery(today.isoformat())
    if data:
        charged = data[0].get("charged", "n/a")
        drained = data[0].get("drained", "n/a")
        print(f"  Charged: {charged}  Drained: {drained}")


if __name__ == "__main__":
    client = get_client()
    today = date.today()

    show_stats(client, today)
    show_activities(client, limit=10)

    # Show detail for most recent de-duplicated activity
    raw = client.get_activities(0, 20)
    deduped = _dedup_activities(raw)
    if deduped:
        most_recent_id = deduped[0].get("activityId")
        if most_recent_id:
            show_activity_detail(client, str(most_recent_id))

    show_sleep(client, today)
    show_hrv(client, today)
    show_body_battery(client, today)
    show_weekly_trends(client, today, weeks=4)

    print("\nDone.")
