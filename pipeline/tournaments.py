"""Real World Cup and European Championship hosts and dates (1950-2026).

Each entry: (type, year, host label, final-venue city, lat, lon, start "YYYY-MM", end "YYYY-MM").
The final-venue city is used as the hub location. Audience weights are NOT here;
the pipeline sizes tournaments relative to club hubs (see hotspots.py).
"""

TOURNAMENTS = [
    # FIFA World Cup
    ("World Cup", 1950, "Brazil", "Rio de Janeiro", -22.91, -43.17, "1950-06", "1950-07"),
    ("World Cup", 1954, "Switzerland", "Bern", 46.95, 7.45, "1954-06", "1954-07"),
    ("World Cup", 1958, "Sweden", "Stockholm", 59.33, 18.07, "1958-06", "1958-06"),
    ("World Cup", 1962, "Chile", "Santiago", -33.45, -70.67, "1962-05", "1962-06"),
    ("World Cup", 1966, "England", "London", 51.51, -0.13, "1966-07", "1966-07"),
    ("World Cup", 1970, "Mexico", "Mexico City", 19.43, -99.13, "1970-05", "1970-06"),
    ("World Cup", 1974, "West Germany", "Munich", 48.14, 11.58, "1974-06", "1974-07"),
    ("World Cup", 1978, "Argentina", "Buenos Aires", -34.60, -58.38, "1978-06", "1978-06"),
    ("World Cup", 1982, "Spain", "Madrid", 40.42, -3.70, "1982-06", "1982-07"),
    ("World Cup", 1986, "Mexico", "Mexico City", 19.43, -99.13, "1986-05", "1986-06"),
    ("World Cup", 1990, "Italy", "Rome", 41.90, 12.50, "1990-06", "1990-07"),
    ("World Cup", 1994, "United States", "Los Angeles", 34.05, -118.24, "1994-06", "1994-07"),
    ("World Cup", 1998, "France", "Paris", 48.86, 2.35, "1998-06", "1998-07"),
    ("World Cup", 2002, "South Korea & Japan", "Yokohama", 35.44, 139.64, "2002-05", "2002-06"),
    ("World Cup", 2006, "Germany", "Berlin", 52.52, 13.40, "2006-06", "2006-07"),
    ("World Cup", 2010, "South Africa", "Johannesburg", -26.20, 28.05, "2010-06", "2010-07"),
    ("World Cup", 2014, "Brazil", "Rio de Janeiro", -22.91, -43.17, "2014-06", "2014-07"),
    ("World Cup", 2018, "Russia", "Moscow", 55.76, 37.62, "2018-06", "2018-07"),
    ("World Cup", 2022, "Qatar", "Lusail", 25.42, 51.49, "2022-11", "2022-12"),
    ("World Cup", 2026, "USA, Canada & Mexico", "New York / New Jersey", 40.81, -74.07, "2026-06", "2026-07"),
    # UEFA European Championship
    ("Euro", 1960, "France", "Paris", 48.86, 2.35, "1960-07", "1960-07"),
    ("Euro", 1964, "Spain", "Madrid", 40.42, -3.70, "1964-06", "1964-06"),
    ("Euro", 1968, "Italy", "Rome", 41.90, 12.50, "1968-06", "1968-06"),
    ("Euro", 1972, "Belgium", "Brussels", 50.85, 4.35, "1972-06", "1972-06"),
    ("Euro", 1976, "Yugoslavia", "Belgrade", 44.79, 20.45, "1976-06", "1976-06"),
    ("Euro", 1980, "Italy", "Rome", 41.90, 12.50, "1980-06", "1980-06"),
    ("Euro", 1984, "France", "Paris", 48.86, 2.35, "1984-06", "1984-06"),
    ("Euro", 1988, "West Germany", "Munich", 48.14, 11.58, "1988-06", "1988-06"),
    ("Euro", 1992, "Sweden", "Gothenburg", 57.71, 11.97, "1992-06", "1992-06"),
    ("Euro", 1996, "England", "London", 51.51, -0.13, "1996-06", "1996-06"),
    ("Euro", 2000, "Belgium & Netherlands", "Rotterdam", 51.92, 4.48, "2000-06", "2000-07"),
    ("Euro", 2004, "Portugal", "Lisbon", 38.72, -9.14, "2004-06", "2004-07"),
    ("Euro", 2008, "Austria & Switzerland", "Vienna", 48.21, 16.37, "2008-06", "2008-06"),
    ("Euro", 2012, "Poland & Ukraine", "Kyiv", 50.45, 30.52, "2012-06", "2012-07"),
    ("Euro", 2016, "France", "Paris", 48.86, 2.35, "2016-06", "2016-07"),
    ("Euro", 2021, "Pan-European (Euro 2020)", "London", 51.51, -0.13, "2021-06", "2021-07"),
    ("Euro", 2024, "Germany", "Berlin", 52.52, 13.40, "2024-06", "2024-07"),
]
