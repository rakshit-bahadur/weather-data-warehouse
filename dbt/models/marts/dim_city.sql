-- One row per city with its location and the date range of available data.

select
    city,
    max(state)          as state,
    max(latitude)       as latitude,
    max(longitude)      as longitude,
    case
        when max(latitude) >= 23.5 then 'North'
        when max(latitude) >= 17.0 then 'Central'
        else 'South'
    end                 as region,
    min(weather_date)   as first_date,
    max(weather_date)   as last_date,
    count(*)            as days_of_data
from {{ ref('stg_weather_daily') }}
group by city
