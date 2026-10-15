-- Clean, typed daily weather. Keeps only the latest load for each city and day.

with source as (

    select * from {{ source('raw', 'weather_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by city, weather_date
            order by loaded_at desc
        ) as row_rank
    from source

)

select
    {{ dbt_utils_surrogate_key(['city', 'weather_date']) }} as weather_day_id,
    trim(city)                                as city,
    trim(state)                               as state,
    cast(latitude as double)                  as latitude,
    cast(longitude as double)                 as longitude,
    cast(weather_date as date)                as weather_date,
    round(temperature_2m_max, 1)              as temp_max_c,
    round(temperature_2m_min, 1)              as temp_min_c,
    round(temperature_2m_mean, 1)             as temp_mean_c,
    round(temperature_2m_max - temperature_2m_min, 1) as temp_range_c,
    coalesce(precipitation_sum, 0)            as precipitation_mm,
    coalesce(rain_sum, 0)                     as rain_mm,
    coalesce(rain_sum, 0) > 0                 as is_rainy_day,
    relative_humidity_2m_mean                 as humidity_pct,
    wind_speed_10m_max                        as wind_max_kmh,
    run_id,
    loaded_at
from ranked
where row_rank = 1
  and temperature_2m_mean is not null
