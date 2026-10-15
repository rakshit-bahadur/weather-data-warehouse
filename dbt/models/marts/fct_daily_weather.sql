-- Daily weather facts with a 7-day rolling average for trend charts.

select
    w.weather_day_id,
    w.city,
    c.region,
    w.weather_date,
    extract(year from w.weather_date)   as year,
    extract(month from w.weather_date)  as month,
    w.temp_max_c,
    w.temp_min_c,
    w.temp_mean_c,
    w.temp_range_c,
    round(avg(w.temp_mean_c) over (
        partition by w.city
        order by w.weather_date
        rows between 6 preceding and current row
    ), 2)                               as temp_mean_7d_avg_c,
    w.precipitation_mm,
    w.rain_mm,
    w.is_rainy_day,
    w.humidity_pct,
    w.wind_max_kmh
from {{ ref('stg_weather_daily') }} w
join {{ ref('dim_city') }} c using (city)
