from __future__ import annotations

# Frozen static fallbacks from the V13.10 champion. V14's leakage-safe prior
# park runtime can replace these when a valid completed-season venue factor is
# available; these values remain the fail-closed baseline.
STATIC_PARK = {
    "Arizona Diamondbacks": 1.04,
    "Athletics": 1.05,
    "Atlanta Braves": 1.01,
    "Baltimore Orioles": 1.01,
    "Boston Red Sox": 1.03,
    "Chicago White Sox": 1.00,
    "Chicago Cubs": 1.02,
    "Cincinnati Reds": 1.05,
    "Cleveland Guardians": 0.98,
    "Colorado Rockies": 1.14,
    "Detroit Tigers": 0.98,
    "Houston Astros": 1.00,
    "Kansas City Royals": 0.99,
    "Los Angeles Angels": 1.01,
    "Los Angeles Dodgers": 0.98,
    "Miami Marlins": 0.96,
    "Milwaukee Brewers": 1.00,
    "Minnesota Twins": 0.99,
    "New York Mets": 0.98,
    "New York Yankees": 1.03,
    "Philadelphia Phillies": 1.02,
    "Pittsburgh Pirates": 0.97,
    "San Diego Padres": 0.97,
    "San Francisco Giants": 0.94,
    "Seattle Mariners": 0.96,
    "St. Louis Cardinals": 1.00,
    "Tampa Bay Rays": 0.98,
    "Texas Rangers": 1.02,
    "Toronto Blue Jays": 1.01,
    "Washington Nationals": 1.00,
}

# Same venue-location approximation used by the working champion's travel/rest
# feature. It is intentionally preserved for parity before any travel-model
# challenger is tested.
TEAM_COORD = {
    "Arizona Diamondbacks": (33.4453, -112.0667),
    "Athletics": (38.5806, -121.5130),
    "Atlanta Braves": (33.8907, -84.4677),
    "Baltimore Orioles": (39.2839, -76.6217),
    "Boston Red Sox": (42.3467, -71.0972),
    "Chicago White Sox": (41.8301, -87.6338),
    "Chicago Cubs": (41.9484, -87.6553),
    "Cincinnati Reds": (39.0975, -84.5069),
    "Cleveland Guardians": (41.4962, -81.6852),
    "Colorado Rockies": (39.7559, -104.9942),
    "Detroit Tigers": (42.3390, -83.0485),
    "Houston Astros": (29.7573, -95.3555),
    "Kansas City Royals": (39.0517, -94.4803),
    "Los Angeles Angels": (33.8003, -117.8827),
    "Los Angeles Dodgers": (34.0739, -118.2400),
    "Miami Marlins": (25.7781, -80.2197),
    "Milwaukee Brewers": (43.0280, -87.9712),
    "Minnesota Twins": (44.9817, -93.2776),
    "New York Mets": (40.7571, -73.8458),
    "New York Yankees": (40.8296, -73.9262),
    "Philadelphia Phillies": (39.9061, -75.1665),
    "Pittsburgh Pirates": (40.4469, -80.0057),
    "San Diego Padres": (32.7076, -117.1570),
    "San Francisco Giants": (37.7786, -122.3893),
    "Seattle Mariners": (47.5914, -122.3325),
    "St. Louis Cardinals": (38.6226, -90.1928),
    "Tampa Bay Rays": (27.7683, -82.6534),
    "Texas Rangers": (32.7473, -97.0832),
    "Toronto Blue Jays": (43.6414, -79.3894),
    "Washington Nationals": (38.8730, -77.0074),
}

LINEUP_WEIGHTS = (1.04, 1.05, 1.08, 1.10, 1.06, 1.00, .96, .93, .90)
