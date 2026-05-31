from garmin_mcp import get_sedentary_analysis, client
from datetime import date, timedelta

today = date.today()
c = client()

print(
    f"{'Date':<12} {'Sed':>5} {'Light':>6} {'Mod':>5} {'Active':>7} {'Streak':>8} {'Breaks':>7} {'Steps':>7} {'ActiveKcal':>11}"
)
print("-" * 80)

for i in range(1, 7):
    r = get_sedentary_analysis(i)
    d = (today - timedelta(days=i)).isoformat()
    stats = c.get_stats(d)
    active_kcal = stats.get("activeKilocalories", 0)
    steps = stats.get("totalSteps", 0)
    th = r.get("time_hours", {})
    streak = r.get("longest_sedentary_streak_min", 0)
    breaks = r.get("activity_breaks_count", 0)
    print(
        f"{r['date']:<12}"
        f"{th.get('sedentary', 0):>5.1f}h"
        f"{th.get('light', 0):>6.1f}h"
        f"{th.get('moderate', 0):>5.1f}h"
        f"{th.get('active', 0):>7.1f}h"
        f"{streak:>7}min"
        f"{breaks:>7}"
        f"{steps:>8}"
        f"{active_kcal:>11}"
    )
