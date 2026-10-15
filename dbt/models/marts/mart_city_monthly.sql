-- Monthly summary per city: temperature, rainfall and humidity.

select
    city,
    region,
    cast(date_trunc('month', weather_date) as date) as month_start,
    count(*)                            as days_observed,
    round(avg(temp_mean_c), 2)          as avg_temp_c,
    max(temp_max_c)                     as hottest_c,
    min(temp_min_c)                     as coldest_c,
    round(sum(rain_mm), 1)              as total_rain_mm,
    sum(case when is_rainy_day then 1 else 0 end) as rainy_days,
    round(avg(humidity_pct), 1)         as avg_humidity_pct,
    max(wind_max_kmh)                   as max_wind_kmh
from {{ ref('fct_daily_weather') }}
group by city, region, date_trunc('month', weather_date)
