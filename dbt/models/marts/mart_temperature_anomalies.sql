-- Flags days whose mean temperature is far from the city's recent baseline.
-- Baseline = the previous N days (var anomaly_window_days), excluding the day itself.

{% set window_days = var('anomaly_window_days') %}
{% set z_threshold = var('anomaly_z_threshold') %}

with baseline as (

    select
        weather_day_id,
        city,
        region,
        weather_date,
        temp_mean_c,
        avg(temp_mean_c) over w         as baseline_mean_c,
        stddev_samp(temp_mean_c) over w as baseline_std_c,
        count(temp_mean_c) over w       as baseline_days
    from {{ ref('fct_daily_weather') }}
    window w as (
        partition by city
        order by weather_date
        rows between {{ window_days }} preceding and 1 preceding
    )

),

scored as (

    select
        *,
        case
            when baseline_std_c > 0
                then round((temp_mean_c - baseline_mean_c) / baseline_std_c, 2)
        end as z_score
    from baseline
    where baseline_days >= {{ window_days // 2 }}

)

select
    weather_day_id,
    city,
    region,
    weather_date,
    temp_mean_c,
    round(baseline_mean_c, 2) as baseline_mean_c,
    round(baseline_std_c, 2)  as baseline_std_c,
    z_score,
    case
        when z_score >= {{ z_threshold }} then 'HEAT_ANOMALY'
        when z_score <= -{{ z_threshold }} then 'COLD_ANOMALY'
    end as anomaly_type
from scored
where abs(z_score) >= {{ z_threshold }}
