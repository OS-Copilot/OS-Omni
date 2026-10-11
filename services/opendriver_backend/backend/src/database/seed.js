const { calculateHaversineDistance, estimateTripDuration, hashPassword, now } = require("../domain");

const sharedPassword = "Password123!";

const rawServiceCities = [
  {
    id: "los_angeles",
    name: "Los Angeles",
    region: "CA",
    centerLatitude: 34.0522,
    centerLongitude: -118.2437,
    radiusKm: 85,
    locations: [
      ["downtown_la", "Downtown Los Angeles, CA", 34.0522, -118.2437],
      ["hollywood", "Hollywood Boulevard, Los Angeles, CA", 34.1016, -118.3267],
      ["santa_monica", "Santa Monica Pier, Santa Monica, CA", 34.0100, -118.4960],
      ["lax", "Los Angeles International Airport (LAX), CA", 33.9416, -118.4085],
      ["griffith", "Griffith Observatory, Los Angeles, CA", 34.1184, -118.3004],
      ["ucla", "UCLA, Los Angeles, CA", 34.0689, -118.4452],
      ["crypto_arena", "Crypto.com Arena, Los Angeles, CA", 34.0430, -118.2673],
      ["pasadena", "Pasadena City Hall, Pasadena, CA", 34.1478, -118.1445]
    ]
  },
  {
    id: "new_york",
    name: "New York City",
    region: "NY",
    centerLatitude: 40.7580,
    centerLongitude: -73.9855,
    radiusKm: 70,
    locations: [
      ["times_square", "Times Square, New York, NY", 40.7580, -73.9855],
      ["penn_station", "Penn Station, New York, NY", 40.7506, -73.9935],
      ["jfk", "John F. Kennedy International Airport (JFK), Queens, NY", 40.6413, -73.7781],
      ["laguardia", "LaGuardia Airport (LGA), Queens, NY", 40.7769, -73.8740],
      ["brooklyn_heights", "Brooklyn Heights, Brooklyn, NY", 40.6959, -73.9936],
      ["williamsburg", "Williamsburg, Brooklyn, NY", 40.7081, -73.9571],
      ["central_park", "Central Park South, New York, NY", 40.7644, -73.9738],
      ["nyu", "New York University, Greenwich Village, New York, NY", 40.7295, -73.9965],
      ["metlife", "MetLife Stadium, East Rutherford, NJ", 40.8135, -74.0745]
    ]
  },
  {
    id: "san_diego",
    name: "San Diego",
    region: "CA",
    centerLatitude: 32.7157,
    centerLongitude: -117.1611,
    radiusKm: 65,
    locations: [
      ["downtown_san_diego", "Downtown San Diego, CA", 32.7157, -117.1611],
      ["san_diego_airport", "San Diego International Airport (SAN), CA", 32.7338, -117.1933],
      ["gaslamp_quarter", "Gaslamp Quarter, San Diego, CA", 32.7115, -117.1600],
      ["balboa_park", "Balboa Park, San Diego, CA", 32.7341, -117.1446],
      ["uc_san_diego", "UC San Diego, La Jolla, CA", 32.8801, -117.2340],
      ["la_jolla_cove", "La Jolla Cove, San Diego, CA", 32.8509, -117.2729],
      ["mission_valley", "Mission Valley, San Diego, CA", 32.7712, -117.1570]
    ]
  },
  {
    id: "san_jose",
    name: "San Jose",
    region: "CA",
    centerLatitude: 37.3382,
    centerLongitude: -121.8863,
    radiusKm: 65,
    locations: [
      ["downtown_san_jose", "Downtown San Jose, CA", 37.3382, -121.8863],
      ["sjc_airport", "San Jose Mineta International Airport (SJC), CA", 37.3639, -121.9289],
      ["santana_row", "Santana Row, San Jose, CA", 37.3205, -121.9472],
      ["san_jose_state", "San Jose State University, San Jose, CA", 37.3352, -121.8811],
      ["sap_center", "SAP Center, San Jose, CA", 37.3328, -121.9012],
      ["willow_glen", "Willow Glen, San Jose, CA", 37.3088, -121.9001],
      ["north_san_jose", "North San Jose, CA", 37.3875, -121.9290]
    ]
  },
  {
    id: "buffalo",
    name: "Buffalo",
    region: "NY",
    centerLatitude: 42.8864,
    centerLongitude: -78.8784,
    radiusKm: 55,
    locations: [
      ["downtown_buffalo", "Downtown Buffalo, NY", 42.8864, -78.8784],
      ["buffalo_airport", "Buffalo Niagara International Airport (BUF), NY", 42.9405, -78.7322],
      ["canalside_buffalo", "Canalside, Buffalo, NY", 42.8750, -78.8770],
      ["university_at_buffalo", "University at Buffalo North Campus, Amherst, NY", 43.0008, -78.7890],
      ["elmwood_village", "Elmwood Village, Buffalo, NY", 42.9177, -78.8760],
      ["keybank_center", "KeyBank Center, Buffalo, NY", 42.8750, -78.8766],
      ["buffalo_medical_campus", "Buffalo Niagara Medical Campus, Buffalo, NY", 42.9006, -78.8661]
    ]
  },
  {
    id: "rochester_ny",
    name: "Rochester",
    region: "NY",
    centerLatitude: 43.1566,
    centerLongitude: -77.6088,
    radiusKm: 55,
    locations: [
      ["downtown_rochester_ny", "Downtown Rochester, NY", 43.1566, -77.6088],
      ["roc_airport", "Frederick Douglass Greater Rochester International Airport (ROC), NY", 43.1189, -77.6724],
      ["university_rochester", "University of Rochester, Rochester, NY", 43.1286, -77.6285],
      ["eastman_theatre", "Eastman Theatre, Rochester, NY", 43.1577, -77.6014],
      ["strong_museum", "The Strong National Museum of Play, Rochester, NY", 43.1527, -77.6008],
      ["highland_park_rochester", "Highland Park, Rochester, NY", 43.1306, -77.6088],
      ["rit", "Rochester Institute of Technology, Henrietta, NY", 43.0845, -77.6744]
    ]
  },
  {
    id: "chicago",
    name: "Chicago",
    region: "IL",
    centerLatitude: 41.8781,
    centerLongitude: -87.6298,
    radiusKm: 70,
    locations: [
      ["loop", "The Loop, Chicago, IL", 41.8819, -87.6278],
      ["ohare", "O'Hare International Airport (ORD), Chicago, IL", 41.9742, -87.9073],
      ["midway", "Midway International Airport (MDW), Chicago, IL", 41.7868, -87.7522],
      ["river_north", "River North, Chicago, IL", 41.8924, -87.6341],
      ["wrigley", "Wrigley Field, Chicago, IL", 41.9484, -87.6553],
      ["navy_pier", "Navy Pier, Chicago, IL", 41.8917, -87.6079],
      ["united_center", "United Center, Chicago, IL", 41.8807, -87.6742]
    ]
  },
  {
    id: "sf_bay",
    name: "San Francisco Bay Area",
    region: "CA",
    centerLatitude: 37.4477,
    centerLongitude: -122.1619,
    radiusKm: 85,
    locations: [
      ["university_ave_palo_alto", "University Avenue, Palo Alto, CA", 37.4477, -122.1619],
      ["palo_alto", "Downtown Palo Alto, CA", 37.4419, -122.1430],
      ["stanford", "Stanford University, Stanford, CA", 37.4275, -122.1697],
      ["mountain_view_castro", "Castro Street, Mountain View, CA", 37.3947, -122.0781],
      ["apple_park", "Apple Park, Cupertino, CA", 37.3349, -122.0090],
      ["googleplex", "Googleplex, Mountain View, CA", 37.4220, -122.0841],
      ["sjc", "San Jose Mineta International Airport (SJC), CA", 37.3639, -121.9289],
      ["downtown_sf", "Downtown San Francisco, CA", 37.7749, -122.4194],
      ["sfo", "San Francisco International Airport (SFO), CA", 37.6213, -122.3790],
      ["oakland", "Downtown Oakland, CA", 37.8044, -122.2711],
      ["ferry_building", "Ferry Building, San Francisco, CA", 37.7955, -122.3937],
      ["mission", "Mission District, San Francisco, CA", 37.7599, -122.4148]
    ]
  },
  {
    id: "washington_dc",
    name: "Washington DC",
    region: "DC",
    centerLatitude: 38.9072,
    centerLongitude: -77.0369,
    radiusKm: 65,
    locations: [
      ["national_mall", "National Mall, Washington, DC", 38.8895, -77.0353],
      ["union_station_dc", "Union Station, Washington, DC", 38.8977, -77.0060],
      ["dca", "Ronald Reagan Washington National Airport (DCA), VA", 38.8512, -77.0402],
      ["iad", "Dulles International Airport (IAD), VA", 38.9531, -77.4565],
      ["georgetown", "Georgetown, Washington, DC", 38.9097, -77.0654],
      ["arlington", "Arlington, VA", 38.8797, -77.1068],
      ["bethesda", "Bethesda, MD", 38.9847, -77.0947]
    ]
  },
  {
    id: "miami",
    name: "Miami",
    region: "FL",
    centerLatitude: 25.7617,
    centerLongitude: -80.1918,
    radiusKm: 70,
    locations: [
      ["brickell", "Brickell, Miami, FL", 25.7602, -80.1959],
      ["mia", "Miami International Airport (MIA), FL", 25.7959, -80.2870],
      ["south_beach", "South Beach, Miami Beach, FL", 25.7826, -80.1341],
      ["wynwood", "Wynwood, Miami, FL", 25.8011, -80.1996],
      ["coral_gables", "Coral Gables, FL", 25.7215, -80.2684],
      ["ft_lauderdale", "Fort Lauderdale, FL", 26.1224, -80.1373],
      ["hard_rock", "Hard Rock Stadium, Miami Gardens, FL", 25.9580, -80.2389]
    ]
  },
  {
    id: "seattle",
    name: "Seattle",
    region: "WA",
    centerLatitude: 47.6062,
    centerLongitude: -122.3321,
    radiusKm: 70,
    locations: [
      ["downtown_seattle", "Downtown Seattle, WA", 47.6062, -122.3321],
      ["sea_tac", "Seattle-Tacoma International Airport (SEA), WA", 47.4502, -122.3088],
      ["pike_place", "Pike Place Market, Seattle, WA", 47.6097, -122.3425],
      ["south_lake_union", "South Lake Union, Seattle, WA", 47.6232, -122.3384],
      ["uw", "University of Washington, Seattle, WA", 47.6553, -122.3035],
      ["bellevue", "Downtown Bellevue, WA", 47.6101, -122.2015],
      ["lumen_field", "Lumen Field, Seattle, WA", 47.5952, -122.3316]
    ]
  },
  {
    id: "spokane",
    name: "Spokane",
    region: "WA",
    centerLatitude: 47.6588,
    centerLongitude: -117.4260,
    radiusKm: 55,
    locations: [
      ["downtown_spokane", "Downtown Spokane, WA", 47.6588, -117.4260],
      ["spokane_airport", "Spokane International Airport (GEG), WA", 47.6199, -117.5338],
      ["riverfront_park_spokane", "Riverfront Park, Spokane, WA", 47.6606, -117.4217],
      ["gonzaga", "Gonzaga University, Spokane, WA", 47.6672, -117.4027],
      ["sacred_heart_spokane", "Providence Sacred Heart Medical Center, Spokane, WA", 47.6481, -117.4130],
      ["spokane_valley", "Spokane Valley, WA", 47.6732, -117.2394],
      ["north_spokane", "North Spokane, WA", 47.7205, -117.4110]
    ]
  },
  {
    id: "tacoma",
    name: "Tacoma",
    region: "WA",
    centerLatitude: 47.2529,
    centerLongitude: -122.4443,
    radiusKm: 55,
    locations: [
      ["downtown_tacoma", "Downtown Tacoma, WA", 47.2529, -122.4443],
      ["tacoma_dome", "Tacoma Dome, Tacoma, WA", 47.2365, -122.4265],
      ["university_of_puget_sound", "University of Puget Sound, Tacoma, WA", 47.2639, -122.4815],
      ["point_defiance", "Point Defiance Park, Tacoma, WA", 47.3059, -122.5200],
      ["uw_tacoma", "University of Washington Tacoma, WA", 47.2446, -122.4384],
      ["st_joseph_tacoma", "St. Joseph Medical Center, Tacoma, WA", 47.2490, -122.4574],
      ["lakewood_wa", "Lakewood, WA", 47.1718, -122.5185]
    ]
  },
  {
    id: "dallas",
    name: "Dallas-Fort Worth",
    region: "TX",
    centerLatitude: 32.7767,
    centerLongitude: -96.7970,
    radiusKm: 90,
    locations: [
      ["downtown_dallas", "Downtown Dallas, TX", 32.7767, -96.7970],
      ["dfw", "Dallas Fort Worth International Airport (DFW), TX", 32.8998, -97.0403],
      ["love_field", "Dallas Love Field (DAL), TX", 32.8471, -96.8518],
      ["uptown_dallas", "Uptown Dallas, TX", 32.8003, -96.8016],
      ["deep_ellum", "Deep Ellum, Dallas, TX", 32.7840, -96.7837],
      ["downtown_fort_worth", "Downtown Fort Worth, TX", 32.7555, -97.3308],
      ["att_stadium", "AT&T Stadium, Arlington, TX", 32.7473, -97.0945]
    ]
  },
  {
    id: "houston",
    name: "Houston",
    region: "TX",
    centerLatitude: 29.7604,
    centerLongitude: -95.3698,
    radiusKm: 85,
    locations: [
      ["downtown_houston", "Downtown Houston, TX", 29.7604, -95.3698],
      ["iah", "George Bush Intercontinental Airport (IAH), Houston, TX", 29.9902, -95.3368],
      ["hobby", "William P. Hobby Airport (HOU), Houston, TX", 29.6454, -95.2789],
      ["texas_medical_center", "Texas Medical Center, Houston, TX", 29.7079, -95.3975],
      ["galleria_houston", "The Galleria, Houston, TX", 29.7390, -95.4636],
      ["midtown_houston", "Midtown Houston, TX", 29.7418, -95.3768],
      ["nrg_stadium", "NRG Stadium, Houston, TX", 29.6847, -95.4107]
    ]
  },
  {
    id: "san_antonio",
    name: "San Antonio",
    region: "TX",
    centerLatitude: 29.4241,
    centerLongitude: -98.4936,
    radiusKm: 70,
    locations: [
      ["downtown_san_antonio", "Downtown San Antonio, TX", 29.4241, -98.4936],
      ["sat", "San Antonio International Airport (SAT), TX", 29.5337, -98.4698],
      ["river_walk", "San Antonio River Walk, TX", 29.4252, -98.4916],
      ["alamo", "The Alamo, San Antonio, TX", 29.4260, -98.4861],
      ["pearl_district", "Pearl District, San Antonio, TX", 29.4424, -98.4797],
      ["utsa", "University of Texas at San Antonio, TX", 29.5827, -98.6211],
      ["alamodome", "Alamodome, San Antonio, TX", 29.4169, -98.4789]
    ]
  },
  {
    id: "atlanta",
    name: "Atlanta",
    region: "GA",
    centerLatitude: 33.7490,
    centerLongitude: -84.3880,
    radiusKm: 75,
    locations: [
      ["midtown_atlanta", "Midtown Atlanta, GA", 33.7833, -84.3831],
      ["atl", "Hartsfield-Jackson Atlanta International Airport (ATL), GA", 33.6407, -84.4277],
      ["downtown_atlanta", "Downtown Atlanta, GA", 33.7550, -84.3900],
      ["buckhead", "Buckhead, Atlanta, GA", 33.8484, -84.3733],
      ["ponce_city_market", "Ponce City Market, Atlanta, GA", 33.7726, -84.3656],
      ["mercedes_benz", "Mercedes-Benz Stadium, Atlanta, GA", 33.7554, -84.4008],
      ["decatur", "Decatur, GA", 33.7748, -84.2963]
    ]
  },
  {
    id: "boston",
    name: "Boston",
    region: "MA",
    centerLatitude: 42.3601,
    centerLongitude: -71.0589,
    radiusKm: 60,
    locations: [
      ["downtown_boston", "Downtown Boston, MA", 42.3601, -71.0589],
      ["logan", "Boston Logan International Airport (BOS), MA", 42.3656, -71.0096],
      ["south_station", "South Station, Boston, MA", 42.3523, -71.0552],
      ["back_bay", "Back Bay, Boston, MA", 42.3503, -71.0810],
      ["cambridge", "Kendall Square, Cambridge, MA", 42.3626, -71.0843],
      ["fenway", "Fenway Park, Boston, MA", 42.3467, -71.0972],
      ["harvard", "Harvard Square, Cambridge, MA", 42.3734, -71.1189]
    ]
  },
  {
    id: "worcester",
    name: "Worcester",
    region: "MA",
    centerLatitude: 42.2626,
    centerLongitude: -71.8023,
    radiusKm: 45,
    locations: [
      ["downtown_worcester", "Downtown Worcester, MA", 42.2626, -71.8023],
      ["worcester_union_station", "Union Station, Worcester, MA", 42.2618, -71.7949],
      ["worcester_airport", "Worcester Regional Airport (ORH), MA", 42.2673, -71.8757],
      ["polar_park", "Polar Park, Worcester, MA", 42.2573, -71.8008],
      ["wpi", "Worcester Polytechnic Institute, Worcester, MA", 42.2749, -71.8081],
      ["umass_memorial", "UMass Memorial Medical Center, Worcester, MA", 42.2767, -71.7619],
      ["college_of_holy_cross", "College of the Holy Cross, Worcester, MA", 42.2385, -71.8089]
    ]
  },
  {
    id: "springfield_ma",
    name: "Springfield",
    region: "MA",
    centerLatitude: 42.1015,
    centerLongitude: -72.5898,
    radiusKm: 45,
    locations: [
      ["downtown_springfield_ma", "Downtown Springfield, MA", 42.1015, -72.5898],
      ["springfield_union_station", "Union Station, Springfield, MA", 42.1061, -72.5939],
      ["mgm_springfield", "MGM Springfield, MA", 42.0997, -72.5881],
      ["basketball_hall", "Naismith Basketball Hall of Fame, Springfield, MA", 42.0930, -72.5845],
      ["springfield_college", "Springfield College, Springfield, MA", 42.1057, -72.5562],
      ["baystate_medical", "Baystate Medical Center, Springfield, MA", 42.1209, -72.6044],
      ["forest_park_springfield", "Forest Park, Springfield, MA", 42.0808, -72.5745]
    ]
  },
  {
    id: "detroit",
    name: "Detroit",
    region: "MI",
    centerLatitude: 42.3314,
    centerLongitude: -83.0458,
    radiusKm: 65,
    locations: [
      ["downtown_detroit", "Downtown Detroit, MI", 42.3314, -83.0458],
      ["dtw", "Detroit Metropolitan Wayne County Airport (DTW), MI", 42.2162, -83.3554],
      ["midtown_detroit", "Midtown Detroit, MI", 42.3482, -83.0583],
      ["wayne_state", "Wayne State University, Detroit, MI", 42.3591, -83.0665],
      ["comerica_park", "Comerica Park, Detroit, MI", 42.3390, -83.0485],
      ["henry_ford_hospital", "Henry Ford Hospital, Detroit, MI", 42.3676, -83.0849],
      ["detroit_riverfront", "Detroit Riverfront, Detroit, MI", 42.3270, -83.0392]
    ]
  },
  {
    id: "grand_rapids",
    name: "Grand Rapids",
    region: "MI",
    centerLatitude: 42.9634,
    centerLongitude: -85.6681,
    radiusKm: 45,
    locations: [
      ["downtown_grand_rapids", "Downtown Grand Rapids, MI", 42.9634, -85.6681],
      ["grr", "Gerald R. Ford International Airport (GRR), MI", 42.8808, -85.5228],
      ["medical_mile", "Medical Mile, Grand Rapids, MI", 42.9700, -85.6644],
      ["van_andel_arena", "Van Andel Arena, Grand Rapids, MI", 42.9620, -85.6712],
      ["grand_valley_downtown", "Grand Valley State University Pew Campus, Grand Rapids, MI", 42.9631, -85.6757],
      ["east_grand_rapids", "East Grand Rapids, MI", 42.9411, -85.6100],
      ["john_ball_zoo", "John Ball Zoo, Grand Rapids, MI", 42.9636, -85.7043]
    ]
  },
  {
    id: "warren_mi",
    name: "Warren",
    region: "MI",
    centerLatitude: 42.5145,
    centerLongitude: -83.0147,
    radiusKm: 45,
    locations: [
      ["downtown_warren", "Downtown Warren, MI", 42.5145, -83.0147],
      ["gm_tech_center", "General Motors Technical Center, Warren, MI", 42.5188, -83.0390],
      ["warren_city_hall", "Warren City Hall, Warren, MI", 42.5147, -83.0280],
      ["macomb_community_college", "Macomb Community College South Campus, Warren, MI", 42.5208, -82.9643],
      ["ascension_macomb", "Ascension Macomb-Oakland Hospital, Warren, MI", 42.5752, -82.9714],
      ["sterling_heights", "Sterling Heights, MI", 42.5803, -83.0302],
      ["royal_oak", "Royal Oak, MI", 42.4895, -83.1446]
    ]
  },
  {
    id: "toronto",
    name: "Toronto",
    region: "Canada",
    centerLatitude: 43.6532,
    centerLongitude: -79.3832,
    radiusKm: 75,
    locations: [
      ["toronto_downtown", "Downtown Toronto, ON, Canada", 43.6532, -79.3832],
      ["yyz", "Toronto Pearson International Airport (YYZ), ON, Canada", 43.6777, -79.6248],
      ["union_station_toronto", "Union Station, Toronto, ON, Canada", 43.6452, -79.3806],
      ["cn_tower", "CN Tower, Toronto, ON, Canada", 43.6426, -79.3871],
      ["yorkville", "Yorkville, Toronto, ON, Canada", 43.6709, -79.3933],
      ["north_york", "North York Centre, Toronto, ON, Canada", 43.7687, -79.4127]
    ]
  },
  {
    id: "vancouver",
    name: "Vancouver",
    region: "Canada",
    centerLatitude: 49.2827,
    centerLongitude: -123.1207,
    radiusKm: 70,
    locations: [
      ["vancouver_downtown", "Downtown Vancouver, BC, Canada", 49.2827, -123.1207],
      ["yvr", "Vancouver International Airport (YVR), BC, Canada", 49.1967, -123.1815],
      ["waterfront_vancouver", "Waterfront Station, Vancouver, BC, Canada", 49.2858, -123.1119],
      ["gastown", "Gastown, Vancouver, BC, Canada", 49.2828, -123.1067],
      ["kitsilano", "Kitsilano, Vancouver, BC, Canada", 49.2684, -123.1683],
      ["burnaby", "Metrotown, Burnaby, BC, Canada", 49.2276, -123.0076]
    ]
  },
  {
    id: "mexico_city",
    name: "Mexico City",
    region: "Mexico",
    centerLatitude: 19.4326,
    centerLongitude: -99.1332,
    radiusKm: 80,
    locations: [
      ["cdmx_centro", "Centro Historico, Mexico City, Mexico", 19.4326, -99.1332],
      ["mex", "Mexico City International Airport (MEX), Mexico", 19.4361, -99.0719],
      ["polanco", "Polanco, Mexico City, Mexico", 19.4321, -99.1941],
      ["roma_norte", "Roma Norte, Mexico City, Mexico", 19.4194, -99.1641],
      ["condesa", "Condesa, Mexico City, Mexico", 19.4120, -99.1747],
      ["santa_fe_cdmx", "Santa Fe, Mexico City, Mexico", 19.3598, -99.2769]
    ]
  },
  {
    id: "sao_paulo",
    name: "Sao Paulo",
    region: "Brazil",
    centerLatitude: -23.5505,
    centerLongitude: -46.6333,
    radiusKm: 85,
    locations: [
      ["paulista", "Avenida Paulista, Sao Paulo, Brazil", -23.5614, -46.6559],
      ["gru", "Sao Paulo Guarulhos International Airport (GRU), Brazil", -23.4356, -46.4731],
      ["congonhas", "Congonhas Airport (CGH), Sao Paulo, Brazil", -23.6261, -46.6566],
      ["vila_madalena", "Vila Madalena, Sao Paulo, Brazil", -23.5489, -46.6926],
      ["itaim_bibi", "Itaim Bibi, Sao Paulo, Brazil", -23.5846, -46.6786],
      ["pinheiros", "Pinheiros, Sao Paulo, Brazil", -23.5673, -46.7019]
    ]
  },
  {
    id: "rio_de_janeiro",
    name: "Rio de Janeiro",
    region: "Brazil",
    centerLatitude: -22.9068,
    centerLongitude: -43.1729,
    radiusKm: 75,
    locations: [
      ["rio_centro", "Centro, Rio de Janeiro, Brazil", -22.9068, -43.1729],
      ["gig", "Rio de Janeiro Galeao International Airport (GIG), Brazil", -22.8099, -43.2506],
      ["sdu", "Santos Dumont Airport (SDU), Rio de Janeiro, Brazil", -22.9105, -43.1631],
      ["copacabana", "Copacabana, Rio de Janeiro, Brazil", -22.9711, -43.1822],
      ["ipanema", "Ipanema, Rio de Janeiro, Brazil", -22.9847, -43.1986],
      ["barra", "Barra da Tijuca, Rio de Janeiro, Brazil", -23.0004, -43.3659]
    ]
  },
  {
    id: "buenos_aires",
    name: "Buenos Aires",
    region: "Argentina",
    centerLatitude: -34.6037,
    centerLongitude: -58.3816,
    radiusKm: 75,
    locations: [
      ["obelisco", "Obelisco, Buenos Aires, Argentina", -34.6037, -58.3816],
      ["eze", "Ezeiza International Airport (EZE), Buenos Aires, Argentina", -34.8222, -58.5358],
      ["aep", "Aeroparque Jorge Newbery (AEP), Buenos Aires, Argentina", -34.5580, -58.4156],
      ["palermo", "Palermo, Buenos Aires, Argentina", -34.5889, -58.4306],
      ["recoleta", "Recoleta, Buenos Aires, Argentina", -34.5875, -58.3974],
      ["puerto_madero", "Puerto Madero, Buenos Aires, Argentina", -34.6118, -58.3620]
    ]
  },
  {
    id: "santiago",
    name: "Santiago",
    region: "Chile",
    centerLatitude: -33.4489,
    centerLongitude: -70.6693,
    radiusKm: 70,
    locations: [
      ["santiago_centro", "Downtown Santiago, Chile", -33.4489, -70.6693],
      ["scl", "Santiago International Airport (SCL), Chile", -33.3928, -70.7858],
      ["providencia", "Providencia, Santiago, Chile", -33.4263, -70.6170],
      ["las_condes", "Las Condes, Santiago, Chile", -33.4088, -70.5675],
      ["bellavista", "Barrio Bellavista, Santiago, Chile", -33.4326, -70.6345],
      ["vitacura", "Vitacura, Santiago, Chile", -33.3812, -70.5720]
    ]
  },
  {
    id: "bogota",
    name: "Bogota",
    region: "Colombia",
    centerLatitude: 4.7110,
    centerLongitude: -74.0721,
    radiusKm: 70,
    locations: [
      ["bogota_centro", "Downtown Bogota, Colombia", 4.7110, -74.0721],
      ["bog", "El Dorado International Airport (BOG), Bogota, Colombia", 4.7016, -74.1469],
      ["chapinero", "Chapinero, Bogota, Colombia", 4.6486, -74.0628],
      ["zona_t", "Zona T, Bogota, Colombia", 4.6673, -74.0533],
      ["usaquen", "Usaquen, Bogota, Colombia", 4.6959, -74.0308],
      ["la_candelaria", "La Candelaria, Bogota, Colombia", 4.5964, -74.0733]
    ]
  },
  {
    id: "london",
    name: "London",
    region: "United Kingdom",
    centerLatitude: 51.5074,
    centerLongitude: -0.1278,
    radiusKm: 85,
    locations: [
      ["westminster", "Westminster, London, UK", 51.4995, -0.1248],
      ["lhr", "Heathrow Airport (LHR), London, UK", 51.4700, -0.4543],
      ["lgw", "Gatwick Airport (LGW), London, UK", 51.1537, -0.1821],
      ["kings_cross", "King's Cross St Pancras, London, UK", 51.5320, -0.1233],
      ["canary_wharf", "Canary Wharf, London, UK", 51.5054, -0.0235],
      ["shoreditch", "Shoreditch, London, UK", 51.5260, -0.0780],
      ["paddington", "Paddington Station, London, UK", 51.5154, -0.1755]
    ]
  },
  {
    id: "paris",
    name: "Paris",
    region: "France",
    centerLatitude: 48.8566,
    centerLongitude: 2.3522,
    radiusKm: 75,
    locations: [
      ["paris_center", "Hotel de Ville, Paris, France", 48.8566, 2.3522],
      ["cdg", "Charles de Gaulle Airport (CDG), Paris, France", 49.0097, 2.5479],
      ["ory", "Orly Airport (ORY), Paris, France", 48.7262, 2.3652],
      ["gare_du_nord", "Gare du Nord, Paris, France", 48.8809, 2.3553],
      ["la_defense", "La Defense, Paris, France", 48.8924, 2.2369],
      ["eiffel_tower", "Eiffel Tower, Paris, France", 48.8584, 2.2945],
      ["montmartre", "Montmartre, Paris, France", 48.8867, 2.3431]
    ]
  },
  {
    id: "berlin",
    name: "Berlin",
    region: "Germany",
    centerLatitude: 52.5200,
    centerLongitude: 13.4050,
    radiusKm: 70,
    locations: [
      ["mitte", "Mitte, Berlin, Germany", 52.5200, 13.4050],
      ["ber", "Berlin Brandenburg Airport (BER), Germany", 52.3667, 13.5033],
      ["hauptbahnhof", "Berlin Hauptbahnhof, Germany", 52.5251, 13.3694],
      ["alexanderplatz", "Alexanderplatz, Berlin, Germany", 52.5219, 13.4132],
      ["kreuzberg", "Kreuzberg, Berlin, Germany", 52.4986, 13.4034],
      ["potsdamer_platz", "Potsdamer Platz, Berlin, Germany", 52.5096, 13.3760]
    ]
  },
  {
    id: "madrid",
    name: "Madrid",
    region: "Spain",
    centerLatitude: 40.4168,
    centerLongitude: -3.7038,
    radiusKm: 70,
    locations: [
      ["puerta_sol", "Puerta del Sol, Madrid, Spain", 40.4168, -3.7038],
      ["mad", "Adolfo Suarez Madrid-Barajas Airport (MAD), Spain", 40.4983, -3.5676],
      ["atocha", "Madrid Atocha Station, Spain", 40.4065, -3.6896],
      ["salamanca", "Salamanca, Madrid, Spain", 40.4300, -3.6800],
      ["chamartin", "Chamartin, Madrid, Spain", 40.4722, -3.6825],
      ["gran_via", "Gran Via, Madrid, Spain", 40.4203, -3.7058]
    ]
  },
  {
    id: "rome",
    name: "Rome",
    region: "Italy",
    centerLatitude: 41.9028,
    centerLongitude: 12.4964,
    radiusKm: 70,
    locations: [
      ["rome_center", "Centro Storico, Rome, Italy", 41.9028, 12.4964],
      ["fco", "Leonardo da Vinci Fiumicino Airport (FCO), Rome, Italy", 41.8003, 12.2389],
      ["cia", "Ciampino Airport (CIA), Rome, Italy", 41.7999, 12.5949],
      ["termini", "Roma Termini Station, Rome, Italy", 41.9010, 12.5019],
      ["trastevere", "Trastevere, Rome, Italy", 41.8898, 12.4663],
      ["colosseum", "Colosseum, Rome, Italy", 41.8902, 12.4922]
    ]
  },
  {
    id: "amsterdam",
    name: "Amsterdam",
    region: "Netherlands",
    centerLatitude: 52.3676,
    centerLongitude: 4.9041,
    radiusKm: 60,
    locations: [
      ["amsterdam_centraal", "Amsterdam Centraal, Netherlands", 52.3791, 4.8994],
      ["ams", "Amsterdam Schiphol Airport (AMS), Netherlands", 52.3105, 4.7683],
      ["dam_square", "Dam Square, Amsterdam, Netherlands", 52.3731, 4.8922],
      ["jordaan", "Jordaan, Amsterdam, Netherlands", 52.3738, 4.8810],
      ["zuidas", "Zuidas, Amsterdam, Netherlands", 52.3373, 4.8739],
      ["museumplein", "Museumplein, Amsterdam, Netherlands", 52.3579, 4.8812]
    ]
  },
  {
    id: "istanbul",
    name: "Istanbul",
    region: "Turkey",
    centerLatitude: 41.0082,
    centerLongitude: 28.9784,
    radiusKm: 90,
    locations: [
      ["sultanahmet", "Sultanahmet, Istanbul, Turkey", 41.0082, 28.9784],
      ["ist", "Istanbul Airport (IST), Turkey", 41.2753, 28.7519],
      ["saw", "Sabiha Gokcen Airport (SAW), Istanbul, Turkey", 40.8986, 29.3092],
      ["taksim", "Taksim Square, Istanbul, Turkey", 41.0369, 28.9850],
      ["besiktas", "Besiktas, Istanbul, Turkey", 41.0438, 29.0094],
      ["kadikoy", "Kadikoy, Istanbul, Turkey", 40.9903, 29.0290]
    ]
  },
  {
    id: "dubai",
    name: "Dubai",
    region: "United Arab Emirates",
    centerLatitude: 25.2048,
    centerLongitude: 55.2708,
    radiusKm: 85,
    locations: [
      ["downtown_dubai", "Downtown Dubai, UAE", 25.1972, 55.2744],
      ["dxb", "Dubai International Airport (DXB), UAE", 25.2532, 55.3657],
      ["dubai_marina", "Dubai Marina, UAE", 25.0805, 55.1403],
      ["business_bay", "Business Bay, Dubai, UAE", 25.1850, 55.2772],
      ["jbr", "Jumeirah Beach Residence, Dubai, UAE", 25.0750, 55.1313],
      ["palm_jumeirah", "Palm Jumeirah, Dubai, UAE", 25.1124, 55.1390]
    ]
  },
  {
    id: "riyadh",
    name: "Riyadh",
    region: "Saudi Arabia",
    centerLatitude: 24.7136,
    centerLongitude: 46.6753,
    radiusKm: 80,
    locations: [
      ["olaya", "Olaya, Riyadh, Saudi Arabia", 24.7136, 46.6753],
      ["ruh", "King Khalid International Airport (RUH), Riyadh, Saudi Arabia", 24.9576, 46.6988],
      ["kingdom_centre", "Kingdom Centre, Riyadh, Saudi Arabia", 24.7113, 46.6744],
      ["riyadh_front", "Riyadh Front, Saudi Arabia", 24.8415, 46.7356],
      ["diriyah", "Diriyah, Riyadh, Saudi Arabia", 24.7370, 46.5756],
      ["king_abdullah_financial", "King Abdullah Financial District, Riyadh, Saudi Arabia", 24.7628, 46.6400]
    ]
  },
  {
    id: "cairo",
    name: "Cairo",
    region: "Egypt",
    centerLatitude: 30.0444,
    centerLongitude: 31.2357,
    radiusKm: 80,
    locations: [
      ["downtown_cairo", "Downtown Cairo, Egypt", 30.0444, 31.2357],
      ["cai", "Cairo International Airport (CAI), Egypt", 30.1120, 31.4000],
      ["zamalek", "Zamalek, Cairo, Egypt", 30.0610, 31.2194],
      ["new_cairo", "New Cairo, Egypt", 30.0131, 31.4913],
      ["giza", "Giza Pyramids, Giza, Egypt", 29.9792, 31.1342],
      ["nasr_city", "Nasr City, Cairo, Egypt", 30.0561, 31.3300]
    ]
  },
  {
    id: "nairobi",
    name: "Nairobi",
    region: "Kenya",
    centerLatitude: -1.2921,
    centerLongitude: 36.8219,
    radiusKm: 65,
    locations: [
      ["nairobi_cbd", "Nairobi CBD, Kenya", -1.2921, 36.8219],
      ["nbo", "Jomo Kenyatta International Airport (NBO), Nairobi, Kenya", -1.3192, 36.9278],
      ["westlands", "Westlands, Nairobi, Kenya", -1.2676, 36.8108],
      ["kilimani", "Kilimani, Nairobi, Kenya", -1.2925, 36.7854],
      ["upper_hill", "Upper Hill, Nairobi, Kenya", -1.3006, 36.8156],
      ["karen", "Karen, Nairobi, Kenya", -1.3197, 36.7073]
    ]
  },
  {
    id: "johannesburg",
    name: "Johannesburg",
    region: "South Africa",
    centerLatitude: -26.2041,
    centerLongitude: 28.0473,
    radiusKm: 80,
    locations: [
      ["sandton", "Sandton, Johannesburg, South Africa", -26.1076, 28.0567],
      ["jnb", "O. R. Tambo International Airport (JNB), Johannesburg, South Africa", -26.1337, 28.2420],
      ["rosebank", "Rosebank, Johannesburg, South Africa", -26.1450, 28.0417],
      ["melrose_arch", "Melrose Arch, Johannesburg, South Africa", -26.1340, 28.0688],
      ["joburg_cbd", "Johannesburg CBD, South Africa", -26.2041, 28.0473],
      ["fourways", "Fourways, Johannesburg, South Africa", -26.0157, 28.0120]
    ]
  },
  {
    id: "mumbai",
    name: "Mumbai",
    region: "India",
    centerLatitude: 19.0760,
    centerLongitude: 72.8777,
    radiusKm: 85,
    locations: [
      ["bandra_kurla", "Bandra Kurla Complex, Mumbai, India", 19.0667, 72.8675],
      ["bom", "Chhatrapati Shivaji Maharaj International Airport (BOM), Mumbai, India", 19.0896, 72.8656],
      ["colaba", "Colaba, Mumbai, India", 18.9067, 72.8147],
      ["andheri", "Andheri, Mumbai, India", 19.1197, 72.8464],
      ["lower_parel", "Lower Parel, Mumbai, India", 18.9930, 72.8308],
      ["powai", "Powai, Mumbai, India", 19.1176, 72.9060]
    ]
  },
  {
    id: "delhi",
    name: "Delhi NCR",
    region: "India",
    centerLatitude: 28.6139,
    centerLongitude: 77.2090,
    radiusKm: 90,
    locations: [
      ["connaught_place", "Connaught Place, New Delhi, India", 28.6315, 77.2167],
      ["del", "Indira Gandhi International Airport (DEL), Delhi, India", 28.5562, 77.1000],
      ["gurugram", "Cyber City, Gurugram, India", 28.4949, 77.0890],
      ["noida", "Sector 18, Noida, India", 28.5706, 77.3261],
      ["south_delhi", "South Delhi, India", 28.5245, 77.1855],
      ["new_delhi_station", "New Delhi Railway Station, India", 28.6429, 77.2195]
    ]
  },
  {
    id: "bangkok",
    name: "Bangkok",
    region: "Thailand",
    centerLatitude: 13.7563,
    centerLongitude: 100.5018,
    radiusKm: 80,
    locations: [
      ["sukhumvit", "Sukhumvit, Bangkok, Thailand", 13.7373, 100.5600],
      ["bkk", "Suvarnabhumi Airport (BKK), Bangkok, Thailand", 13.6900, 100.7501],
      ["dmk", "Don Mueang International Airport (DMK), Bangkok, Thailand", 13.9126, 100.6068],
      ["siam", "Siam, Bangkok, Thailand", 13.7466, 100.5347],
      ["silom", "Silom, Bangkok, Thailand", 13.7246, 100.5294],
      ["ari", "Ari, Bangkok, Thailand", 13.7800, 100.5447]
    ]
  },
  {
    id: "singapore",
    name: "Singapore",
    region: "Singapore",
    centerLatitude: 1.3521,
    centerLongitude: 103.8198,
    radiusKm: 45,
    locations: [
      ["marina_bay", "Marina Bay, Singapore", 1.2834, 103.8607],
      ["sin", "Changi Airport (SIN), Singapore", 1.3644, 103.9915],
      ["orchard", "Orchard Road, Singapore", 1.3048, 103.8318],
      ["raffles_place", "Raffles Place, Singapore", 1.2840, 103.8513],
      ["bugis", "Bugis, Singapore", 1.3008, 103.8559],
      ["sentosa", "Sentosa, Singapore", 1.2494, 103.8303]
    ]
  },
  {
    id: "tokyo",
    name: "Tokyo",
    region: "Japan",
    centerLatitude: 35.6762,
    centerLongitude: 139.6503,
    radiusKm: 90,
    locations: [
      ["tokyo_station", "Tokyo Station, Tokyo, Japan", 35.6812, 139.7671],
      ["hnd", "Haneda Airport (HND), Tokyo, Japan", 35.5494, 139.7798],
      ["nrt", "Narita International Airport (NRT), Chiba, Japan", 35.7719, 140.3929],
      ["shinjuku", "Shinjuku, Tokyo, Japan", 35.6938, 139.7034],
      ["shibuya", "Shibuya, Tokyo, Japan", 35.6595, 139.7005],
      ["roppongi", "Roppongi, Tokyo, Japan", 35.6628, 139.7314],
      ["ginza", "Ginza, Tokyo, Japan", 35.6717, 139.7650]
    ]
  },
  {
    id: "seoul",
    name: "Seoul",
    region: "South Korea",
    centerLatitude: 37.5665,
    centerLongitude: 126.9780,
    radiusKm: 85,
    locations: [
      ["gangnam", "Gangnam, Seoul, South Korea", 37.4979, 127.0276],
      ["icn", "Incheon International Airport (ICN), South Korea", 37.4602, 126.4407],
      ["gmp", "Gimpo International Airport (GMP), Seoul, South Korea", 37.5583, 126.7906],
      ["hongdae", "Hongdae, Seoul, South Korea", 37.5563, 126.9236],
      ["myeongdong", "Myeongdong, Seoul, South Korea", 37.5636, 126.9820],
      ["itaewon", "Itaewon, Seoul, South Korea", 37.5345, 126.9946]
    ]
  },
  {
    id: "hong_kong",
    name: "Hong Kong",
    region: "Hong Kong",
    centerLatitude: 22.3193,
    centerLongitude: 114.1694,
    radiusKm: 55,
    locations: [
      ["central_hk", "Central, Hong Kong", 22.2819, 114.1589],
      ["hkg", "Hong Kong International Airport (HKG)", 22.3080, 113.9185],
      ["tsim_sha_tsui", "Tsim Sha Tsui, Hong Kong", 22.2976, 114.1722],
      ["causeway_bay", "Causeway Bay, Hong Kong", 22.2803, 114.1848],
      ["mong_kok", "Mong Kok, Hong Kong", 22.3193, 114.1694],
      ["kowloon_station", "Kowloon Station, Hong Kong", 22.3048, 114.1615]
    ]
  },
  {
    id: "taipei",
    name: "Taipei",
    region: "Taiwan",
    centerLatitude: 25.0330,
    centerLongitude: 121.5654,
    radiusKm: 70,
    locations: [
      ["taipei_101", "Taipei 101, Taipei, Taiwan", 25.0339, 121.5645],
      ["tpe", "Taoyuan International Airport (TPE), Taiwan", 25.0797, 121.2342],
      ["tsa", "Taipei Songshan Airport (TSA), Taiwan", 25.0694, 121.5525],
      ["taipei_main", "Taipei Main Station, Taiwan", 25.0478, 121.5170],
      ["xinyi", "Xinyi District, Taipei, Taiwan", 25.0330, 121.5654],
      ["ximending", "Ximending, Taipei, Taiwan", 25.0420, 121.5070]
    ]
  },
  {
    id: "shanghai",
    name: "Shanghai",
    region: "China",
    centerLatitude: 31.2304,
    centerLongitude: 121.4737,
    radiusKm: 90,
    locations: [
      ["people_square", "People's Square, Shanghai, China", 31.2304, 121.4737],
      ["pvg", "Shanghai Pudong International Airport (PVG), China", 31.1443, 121.8083],
      ["sha", "Shanghai Hongqiao International Airport (SHA), China", 31.1979, 121.3363],
      ["lujiazui", "Lujiazui, Shanghai, China", 31.2397, 121.4998],
      ["xintiandi", "Xintiandi, Shanghai, China", 31.2199, 121.4751],
      ["jing_an", "Jing'an, Shanghai, China", 31.2231, 121.4454]
    ]
  },
  {
    id: "beijing",
    name: "Beijing",
    region: "China",
    centerLatitude: 39.9042,
    centerLongitude: 116.4074,
    radiusKm: 95,
    locations: [
      ["guomao", "Guomao, Beijing, China", 39.9097, 116.4619],
      ["pek", "Beijing Capital International Airport (PEK), China", 40.0799, 116.6031],
      ["pkx", "Beijing Daxing International Airport (PKX), China", 39.5098, 116.4105],
      ["sanlitun", "Sanlitun, Beijing, China", 39.9336, 116.4551],
      ["wangfujing", "Wangfujing, Beijing, China", 39.9150, 116.4110],
      ["beijing_south", "Beijing South Railway Station, China", 39.8652, 116.3785]
    ]
  },
  {
    id: "sydney",
    name: "Sydney",
    region: "Australia",
    centerLatitude: -33.8688,
    centerLongitude: 151.2093,
    radiusKm: 80,
    locations: [
      ["sydney_cbd", "Sydney CBD, NSW, Australia", -33.8688, 151.2093],
      ["syd", "Sydney Airport (SYD), NSW, Australia", -33.9399, 151.1753],
      ["circular_quay", "Circular Quay, Sydney, Australia", -33.8610, 151.2128],
      ["darling_harbour", "Darling Harbour, Sydney, Australia", -33.8749, 151.2009],
      ["bondi", "Bondi Beach, Sydney, Australia", -33.8915, 151.2767],
      ["parramatta", "Parramatta, Sydney, Australia", -33.8136, 151.0034]
    ]
  },
  {
    id: "melbourne",
    name: "Melbourne",
    region: "Australia",
    centerLatitude: -37.8136,
    centerLongitude: 144.9631,
    radiusKm: 80,
    locations: [
      ["melbourne_cbd", "Melbourne CBD, VIC, Australia", -37.8136, 144.9631],
      ["mel", "Melbourne Airport (MEL), VIC, Australia", -37.6690, 144.8410],
      ["southern_cross", "Southern Cross Station, Melbourne, Australia", -37.8183, 144.9525],
      ["southbank", "Southbank, Melbourne, Australia", -37.8210, 144.9646],
      ["st_kilda", "St Kilda, Melbourne, Australia", -37.8679, 144.9800],
      ["docklands", "Docklands, Melbourne, Australia", -37.8152, 144.9469]
    ]
  },
  {
    id: "auckland",
    name: "Auckland",
    region: "New Zealand",
    centerLatitude: -36.8485,
    centerLongitude: 174.7633,
    radiusKm: 70,
    locations: [
      ["auckland_cbd", "Auckland CBD, New Zealand", -36.8485, 174.7633],
      ["akl", "Auckland Airport (AKL), New Zealand", -37.0082, 174.7850],
      ["viaduct_harbour", "Viaduct Harbour, Auckland, New Zealand", -36.8422, 174.7619],
      ["newmarket", "Newmarket, Auckland, New Zealand", -36.8702, 174.7776],
      ["parnell", "Parnell, Auckland, New Zealand", -36.8567, 174.7810],
      ["takapuna", "Takapuna, Auckland, New Zealand", -36.7869, 174.7732]
    ]
  },
  {
    id: "kuala_lumpur",
    name: "Kuala Lumpur",
    region: "Malaysia",
    centerLatitude: 3.1390,
    centerLongitude: 101.6869,
    radiusKm: 85,
    locations: [
      ["klcc", "KLCC, Kuala Lumpur, Malaysia", 3.1579, 101.7123],
      ["kul", "Kuala Lumpur International Airport (KUL), Malaysia", 2.7456, 101.7072],
      ["bukit_bintang", "Bukit Bintang, Kuala Lumpur, Malaysia", 3.1466, 101.7110],
      ["sentral_kl", "KL Sentral, Kuala Lumpur, Malaysia", 3.1340, 101.6869],
      ["bangsar", "Bangsar, Kuala Lumpur, Malaysia", 3.1290, 101.6797],
      ["mont_kiara", "Mont Kiara, Kuala Lumpur, Malaysia", 3.1677, 101.6508]
    ]
  },
  {
    id: "jakarta",
    name: "Jakarta",
    region: "Indonesia",
    centerLatitude: -6.2088,
    centerLongitude: 106.8456,
    radiusKm: 90,
    locations: [
      ["jakarta_cbd", "Sudirman CBD, Jakarta, Indonesia", -6.2241, 106.8090],
      ["cgk", "Soekarno-Hatta International Airport (CGK), Jakarta, Indonesia", -6.1275, 106.6537],
      ["gambir", "Gambir Station, Jakarta, Indonesia", -6.1767, 106.8307],
      ["kemang", "Kemang, Jakarta, Indonesia", -6.2607, 106.8164],
      ["scbd", "SCBD, Jakarta, Indonesia", -6.2275, 106.8075],
      ["kelapa_gading", "Kelapa Gading, Jakarta, Indonesia", -6.1579, 106.9051]
    ]
  },
  {
    id: "manila",
    name: "Manila",
    region: "Philippines",
    centerLatitude: 14.5995,
    centerLongitude: 120.9842,
    radiusKm: 85,
    locations: [
      ["bgc", "Bonifacio Global City, Metro Manila, Philippines", 14.5503, 121.0505],
      ["mnl", "Ninoy Aquino International Airport (MNL), Manila, Philippines", 14.5086, 121.0194],
      ["makati", "Makati CBD, Metro Manila, Philippines", 14.5547, 121.0244],
      ["intramuros", "Intramuros, Manila, Philippines", 14.5896, 120.9747],
      ["ortigas", "Ortigas Center, Metro Manila, Philippines", 14.5869, 121.0614],
      ["quezon_city", "Quezon City, Metro Manila, Philippines", 14.6760, 121.0437]
    ]
  },
  {
    id: "lagos",
    name: "Lagos",
    region: "Nigeria",
    centerLatitude: 6.5244,
    centerLongitude: 3.3792,
    radiusKm: 80,
    locations: [
      ["victoria_island", "Victoria Island, Lagos, Nigeria", 6.4281, 3.4219],
      ["los", "Murtala Muhammed International Airport (LOS), Lagos, Nigeria", 6.5774, 3.3212],
      ["ikeja", "Ikeja, Lagos, Nigeria", 6.6018, 3.3515],
      ["lekki", "Lekki Phase 1, Lagos, Nigeria", 6.4478, 3.4723],
      ["yaba", "Yaba, Lagos, Nigeria", 6.5158, 3.3873],
      ["marina_lagos", "Lagos Marina, Nigeria", 6.4500, 3.4000]
    ]
  },
  {
    id: "casablanca",
    name: "Casablanca",
    region: "Morocco",
    centerLatitude: 33.5731,
    centerLongitude: -7.5898,
    radiusKm: 70,
    locations: [
      ["casablanca_centre", "Casablanca City Center, Morocco", 33.5731, -7.5898],
      ["cmn", "Mohammed V International Airport (CMN), Casablanca, Morocco", 33.3675, -7.5898],
      ["maarif", "Maarif, Casablanca, Morocco", 33.5833, -7.6333],
      ["ain_diab", "Ain Diab, Casablanca, Morocco", 33.5942, -7.6901],
      ["casa_port", "Casa-Port Railway Station, Casablanca, Morocco", 33.5975, -7.6139],
      ["hassan_ii", "Hassan II Mosque, Casablanca, Morocco", 33.6084, -7.6326]
    ]
  },
  {
    id: "lisbon",
    name: "Lisbon",
    region: "Portugal",
    centerLatitude: 38.7223,
    centerLongitude: -9.1393,
    radiusKm: 70,
    locations: [
      ["baixa", "Baixa, Lisbon, Portugal", 38.7110, -9.1378],
      ["lis", "Humberto Delgado Airport (LIS), Lisbon, Portugal", 38.7742, -9.1342],
      ["chiado", "Chiado, Lisbon, Portugal", 38.7103, -9.1430],
      ["belem", "Belem, Lisbon, Portugal", 38.6968, -9.2065],
      ["parque_nacoes", "Parque das Nacoes, Lisbon, Portugal", 38.7680, -9.0950],
      ["cais_sodre", "Cais do Sodre, Lisbon, Portugal", 38.7069, -9.1456]
    ]
  },
  {
    id: "stockholm",
    name: "Stockholm",
    region: "Sweden",
    centerLatitude: 59.3293,
    centerLongitude: 18.0686,
    radiusKm: 70,
    locations: [
      ["stockholm_central", "Stockholm Central Station, Sweden", 59.3306, 18.0597],
      ["arn", "Stockholm Arlanda Airport (ARN), Sweden", 59.6519, 17.9186],
      ["gamla_stan", "Gamla Stan, Stockholm, Sweden", 59.3250, 18.0710],
      ["ostermalm", "Ostermalm, Stockholm, Sweden", 59.3368, 18.0902],
      ["sodermalm", "Sodermalm, Stockholm, Sweden", 59.3158, 18.0707],
      ["kista", "Kista, Stockholm, Sweden", 59.4032, 17.9448]
    ]
  },
  {
    id: "vienna",
    name: "Vienna",
    region: "Austria",
    centerLatitude: 48.2082,
    centerLongitude: 16.3738,
    radiusKm: 65,
    locations: [
      ["stephansplatz", "Stephansplatz, Vienna, Austria", 48.2085, 16.3731],
      ["vie", "Vienna International Airport (VIE), Austria", 48.1103, 16.5697],
      ["wien_hbf", "Wien Hauptbahnhof, Vienna, Austria", 48.1859, 16.3781],
      ["museumsquartier", "MuseumsQuartier, Vienna, Austria", 48.2032, 16.3591],
      ["prater", "Prater, Vienna, Austria", 48.2167, 16.3956],
      ["schonbrunn", "Schonbrunn Palace, Vienna, Austria", 48.1845, 16.3122]
    ]
  },
  {
    id: "zurich",
    name: "Zurich",
    region: "Switzerland",
    centerLatitude: 47.3769,
    centerLongitude: 8.5417,
    radiusKm: 60,
    locations: [
      ["zurich_hb", "Zurich Hauptbahnhof, Switzerland", 47.3780, 8.5402],
      ["zrh", "Zurich Airport (ZRH), Switzerland", 47.4582, 8.5555],
      ["bahnhofstrasse", "Bahnhofstrasse, Zurich, Switzerland", 47.3697, 8.5392],
      ["zurich_west", "Zurich West, Switzerland", 47.3875, 8.5176],
      ["seefeld", "Seefeld, Zurich, Switzerland", 47.3564, 8.5545],
      ["eth_zurich", "ETH Zurich, Switzerland", 47.3763, 8.5480]
    ]
  }
];

const enabledServiceCityIds = [
  "los_angeles",
  "san_diego",
  "san_jose",
  "sf_bay",
  "new_york",
  "buffalo",
  "rochester_ny",
  "chicago",
  "aurora_il",
  "naperville_il",
  "washington_dc",
  "arlington_va",
  "seattle",
  "dallas",
  "houston",
  "san_antonio",
  "detroit",
  "grand_rapids",
  "warren_mi",
  "ann_arbor"
];

const addedServiceCities = [
  {
    id: "aurora_il",
    name: "Aurora",
    region: "IL",
    centerLatitude: 41.7606,
    centerLongitude: -88.3201,
    radiusKm: 45,
    locations: [
      ["downtown_aurora_il", "Downtown Aurora, IL", 41.7606, -88.3201],
      ["aurora_transportation_center", "Aurora Transportation Center, Aurora, IL", 41.7545, -88.3157],
      ["paramount_theatre_aurora", "Paramount Theatre, Aurora, IL", 41.7583, -88.3148],
      ["fox_valley_mall", "Fox Valley Mall, Aurora, IL", 41.7585, -88.2122],
      ["aurora_university", "Aurora University, Aurora, IL", 41.7530, -88.3490],
      ["waubonsee_aurora", "Waubonsee Community College Aurora Downtown, IL", 41.7565, -88.3159],
      ["rivers_edge_park_aurora", "RiverEdge Park, Aurora, IL", 41.7588, -88.3116]
    ]
  },
  {
    id: "naperville_il",
    name: "Naperville",
    region: "IL",
    centerLatitude: 41.7508,
    centerLongitude: -88.1535,
    radiusKm: 45,
    locations: [
      ["downtown_naperville", "Downtown Naperville, IL", 41.7750, -88.1486],
      ["naperville_station", "Naperville Metra Station, Naperville, IL", 41.7791, -88.1459],
      ["north_central_college", "North Central College, Naperville, IL", 41.7754, -88.1420],
      ["riverwalk_naperville", "Naperville Riverwalk, Naperville, IL", 41.7726, -88.1506],
      ["edward_hospital", "Edward Hospital, Naperville, IL", 41.7618, -88.1535],
      ["naper_settlement", "Naper Settlement, Naperville, IL", 41.7718, -88.1535],
      ["95th_street_library", "95th Street Library, Naperville, IL", 41.7086, -88.1972]
    ]
  },
  {
    id: "arlington_va",
    name: "Arlington",
    region: "DC",
    centerLatitude: 38.8797,
    centerLongitude: -77.1068,
    radiusKm: 40,
    locations: [
      ["downtown_arlington_va", "Downtown Arlington, VA", 38.8797, -77.1068],
      ["rosslyn", "Rosslyn, Arlington, VA", 38.8967, -77.0728],
      ["crystal_city", "Crystal City, Arlington, VA", 38.8576, -77.0502],
      ["pentagon_city", "Pentagon City, Arlington, VA", 38.8629, -77.0595],
      ["ballston", "Ballston, Arlington, VA", 38.8829, -77.1116],
      ["national_airport", "Ronald Reagan Washington National Airport (DCA), VA", 38.8512, -77.0402],
      ["arlington_courthouse", "Arlington Courthouse, Arlington, VA", 38.8904, -77.0830]
    ]
  },
  {
    id: "alexandria_va",
    name: "Alexandria",
    region: "DC",
    centerLatitude: 38.8048,
    centerLongitude: -77.0469,
    radiusKm: 40,
    locations: [
      ["old_town_alexandria", "Old Town Alexandria, VA", 38.8048, -77.0469],
      ["king_street_station", "King Street-Old Town Station, Alexandria, VA", 38.8065, -77.0611],
      ["alexandria_waterfront", "Alexandria Waterfront, Alexandria, VA", 38.8033, -77.0392],
      ["carlyle_alexandria", "Carlyle, Alexandria, VA", 38.8059, -77.0631],
      ["del_ray", "Del Ray, Alexandria, VA", 38.8296, -77.0608],
      ["inova_alexandria", "Inova Alexandria Hospital, Alexandria, VA", 38.8248, -77.1056],
      ["george_washington_masonic", "George Washington Masonic National Memorial, Alexandria, VA", 38.8075, -77.0659]
    ]
  },
  {
    id: "ann_arbor",
    name: "Ann Arbor",
    region: "MI",
    centerLatitude: 42.2808,
    centerLongitude: -83.7430,
    radiusKm: 45,
    locations: [
      ["downtown_ann_arbor", "Downtown Ann Arbor, MI", 42.2808, -83.7430],
      ["university_michigan", "University of Michigan, Ann Arbor, MI", 42.2780, -83.7382],
      ["michigan_stadium", "Michigan Stadium, Ann Arbor, MI", 42.2658, -83.7487],
      ["briarwood_mall", "Briarwood Mall, Ann Arbor, MI", 42.2417, -83.7462],
      ["ann_arbor_station", "Ann Arbor Amtrak Station, Ann Arbor, MI", 42.2862, -83.7445],
      ["umich_hospital", "University of Michigan Hospital, Ann Arbor, MI", 42.2835, -83.7274],
      ["kerrytown", "Kerrytown, Ann Arbor, MI", 42.2834, -83.7460]
    ]
  }
];

const serviceCities = [...rawServiceCities, ...addedServiceCities]
  .filter((city) => enabledServiceCityIds.includes(city.id))
  .sort((a, b) => enabledServiceCityIds.indexOf(a.id) - enabledServiceCityIds.indexOf(b.id));

const locations = Object.fromEntries(
  serviceCities.flatMap((city) =>
    city.locations.map(([key, address, latitude, longitude]) => [
      key,
      { id: key, cityId: city.id, address, latitude, longitude }
    ])
  )
);

function user(id, name, email, phone, role) {
  const createdAt = now();
  return {
    id,
    name,
    email,
    phone,
    passwordHash: hashPassword(sharedPassword),
    role,
    profileImageUrl: "",
    isVerified: true,
    createdAt,
    updatedAt: createdAt
  };
}

function driverProfile({
  id,
  userId,
  licenseNumber,
  vehicleMake,
  vehicleModel,
  vehicleYear,
  licensePlate,
  vehicleColor,
  verificationStatus = "approved",
  driverStatus = "online",
  currentLatitude,
  currentLongitude,
  averageRating = 4.9,
  totalTrips = 0,
  createdAt
}) {
  return {
    id,
    userId,
    licenseNumber,
    vehicleMake,
    vehicleModel,
    vehicleYear,
    licensePlate,
    vehicleColor,
    verificationStatus,
    driverStatus,
    currentLatitude,
    currentLongitude,
    averageRating,
    totalTrips,
    createdAt,
    updatedAt: createdAt
  };
}

function isoDaysAgo(daysAgo, hour = 9, minute = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

function fareForRide(distanceKm, durationMinutes, tierMultiplier = 1, surgeMultiplier = 1, discountAmount = 0) {
  const baseFare = 4.5;
  const distanceFare = Number((Math.max(distanceKm, 0.6) * 1.85 * tierMultiplier).toFixed(2));
  const timeFare = Number((Math.max(durationMinutes, 5) * 0.32 * tierMultiplier).toFixed(2));
  const serviceFee = Number((1.75 * tierMultiplier).toFixed(2));
  const subtotalBeforeDiscount = Number(((baseFare + distanceFare + timeFare + serviceFee) * surgeMultiplier).toFixed(2));
  const estimatedTotal = Number(Math.max(8, subtotalBeforeDiscount - discountAmount).toFixed(2));
  return {
    baseFare,
    distanceFare,
    timeFare,
    serviceFee,
    surgeMultiplier,
    subtotalBeforeDiscount,
    discountAmount,
    estimatedTotal,
    currencyCode: "USD",
    currencySymbol: "$",
    currencyDecimals: 2
  };
}

function timelineForRide(status, createdAt, { driverCancelled = false } = {}) {
  const at = (minutes) => new Date(Date.parse(createdAt) + minutes * 60 * 1000).toISOString();
  const timeline = [
    { status: "requested", label: "Ride requested", at: at(0) },
    { status: "searching", label: "Searching for nearby approved drivers", at: at(1) }
  ];
  if (status === "cancelled") {
    timeline.push({ status: "cancelled", label: driverCancelled ? "Driver cancelled" : "Rider cancelled", at: at(4) });
    return timeline;
  }
  timeline.push(
    { status: "accepted", label: "Driver accepted", at: at(3) },
    { status: "driver_arriving", label: "Driver en route", at: at(4) },
    { status: "arrived", label: "Driver arrived", at: at(10) },
    { status: "in_progress", label: "Trip started", at: at(12) },
    { status: "completed", label: "Trip completed", at: at(26) }
  );
  return timeline;
}

function buildThreeMonthRiderExperience({ rider, drivers, driverProfiles }) {
  const driverById = new Map(drivers.map((item) => [item.id, item]));
  const sfDriverProfiles = driverProfiles.filter((profile) =>
    ["drv_profile_primary", "drv_profile_second", "drv_profile_sf"].includes(profile.id)
  );
  const favoritePlaces = [
    { id: "place_rider_home", label: "Home", address: "Downtown Palo Alto, CA", latitude: 37.4419, longitude: -122.1430, lastUsedAt: isoDaysAgo(2, 18), usageCount: 18, pinned: true },
    { id: "place_rider_work", label: "Work", address: "Meta MPK 23, 300 Constitution Drive, Menlo Park, CA", latitude: 37.4803, longitude: -122.1669, lastUsedAt: isoDaysAgo(1, 9), usageCount: 21, pinned: true },
    { id: "place_rider_school", label: "School", address: locations.stanford.address, latitude: locations.stanford.latitude, longitude: locations.stanford.longitude, lastUsedAt: isoDaysAgo(9, 14), usageCount: 6, pinned: false },
    { id: "place_rider_gym", label: "Gym", address: "Equinox Palo Alto, 440 Portage Avenue, Palo Alto, CA", latitude: 37.4266, longitude: -122.1450, lastUsedAt: isoDaysAgo(5, 20), usageCount: 8, pinned: false },
    { id: "place_rider_airport", label: "Airport", address: locations.sfo.address, latitude: locations.sfo.latitude, longitude: locations.sfo.longitude, lastUsedAt: isoDaysAgo(14, 6), usageCount: 4, pinned: true },
    { id: "place_rider_restaurant", label: "Favorite restaurant", address: "Evvia Estiatorio, 420 Emerson Street, Palo Alto, CA", latitude: 37.4441, longitude: -122.1631, lastUsedAt: isoDaysAgo(3, 22), usageCount: 7, pinned: false },
    { id: "place_rider_mall", label: "Mall", address: "Stanford Shopping Center, Palo Alto, CA", latitude: 37.4432, longitude: -122.1716, lastUsedAt: isoDaysAgo(6, 16), usageCount: 5, pinned: false },
    { id: "place_rider_friend", label: "Friend's place", address: "Castro Street, Mountain View, CA", latitude: 37.3947, longitude: -122.0781, lastUsedAt: isoDaysAgo(11, 21), usageCount: 4, pinned: false }
  ];
  const byLabel = Object.fromEntries(favoritePlaces.map((place) => [place.label, place]));
  const scenarios = [
    ["home_to_work", 3, 8, byLabel.Home, byLabel.Work, "standard", "COMMUTE15", 5, "Smooth commute."],
    ["work_to_home", 5, 18, byLabel.Work, byLabel.Home, "plus", "", 5, "Driver knew the best route."],
    ["restaurant_home_night", 8, 23, byLabel["Favorite restaurant"], byLabel.Home, "priority", "NIGHT12", 4, "Late-night pickup felt safe."],
    ["school_mall", 10, 15, byLabel.School, byLabel.Mall, "green", "", 5, "Clean EV."],
    ["airport_dropoff", 14, 6, byLabel.Home, byLabel.Airport, "xl", "AIRPORT10", 5, "Plenty of room for bags."],
    ["airport_return", 17, 20, byLabel.Airport, byLabel.Home, "plus", "", 4, "Pickup area was busy."],
    ["gym_home", 20, 21, byLabel.Gym, byLabel.Home, "standard", "", 5, "Quick short trip."],
    ["friend_home", 22, 22, byLabel["Friend's place"], byLabel.Home, "standard", "", 5, "On time."],
    ["work_mall_surge", 25, 17, byLabel.Work, byLabel.Mall, "priority", "", 4, "Price was higher during rush hour.", { surge: 1.22, support: "price issue" }],
    ["home_school", 28, 13, byLabel.Home, byLabel.School, "green", "", 5, "Good route."],
    ["cancel_wrong_stop", 30, 10, byLabel.Home, byLabel.Gym, "standard", "", null, "", { status: "cancelled", cancelledBy: "rider" }],
    ["driver_cancelled", 33, 19, byLabel.Work, byLabel.Home, "plus", "", null, "", { status: "cancelled", cancelledBy: "driver" }],
    ["payment_retry", 36, 9, byLabel.Home, byLabel.Work, "standard", "COMMUTE15", 5, "Payment retry worked.", { paymentRetry: true }],
    ["lost_item", 39, 18, byLabel.Mall, byLabel.Home, "standard", "", 3, "Left a water bottle.", { support: "lost item" }],
    ["safety_feedback", 42, 23, byLabel["Favorite restaurant"], byLabel.Home, "priority", "NIGHT12", 2, "Driver missed a turn repeatedly.", { support: "safety concern" }],
    ["home_work_2", 45, 8, byLabel.Home, byLabel.Work, "standard", "COMMUTE15", 5, "Reliable commute."],
    ["work_home_2", 47, 18, byLabel.Work, byLabel.Home, "standard", "", null, "", { unrated: true }],
    ["short_restaurant", 50, 12, byLabel.Home, byLabel["Favorite restaurant"], "standard", "", 5, "Very short ride."],
    ["long_sf", 53, 7, byLabel.Home, { address: locations.downtown_sf.address, latitude: locations.downtown_sf.latitude, longitude: locations.downtown_sf.longitude }, "xl", "", 4, "Long but comfortable."],
    ["mall_friend", 56, 16, byLabel.Mall, byLabel["Friend's place"], "plus", "", 5, "Good car."],
    ["weekend_coupon", 59, 11, byLabel.Home, byLabel.Mall, "green", "WEEKEND8", 5, "Weekend coupon applied."],
    ["gym_work", 62, 8, byLabel.Gym, byLabel.Work, "standard", "", 4, "Driver was polite."],
    ["home_airport_cancel", 65, 5, byLabel.Home, byLabel.Airport, "xl", "AIRPORT10", null, "", { status: "cancelled", cancelledBy: "rider" }],
    ["restaurant_friend", 68, 22, byLabel["Favorite restaurant"], byLabel["Friend's place"], "priority", "NIGHT12", 5, "Safe night ride."],
    ["work_school", 71, 13, byLabel.Work, byLabel.School, "plus", "", 5, "Quiet ride."],
    ["home_work_3", 74, 8, byLabel.Home, byLabel.Work, "standard", "COMMUTE15", 5, "On time."],
    ["work_home_3", 76, 18, byLabel.Work, byLabel.Home, "standard", "", 4, "Traffic was heavy."],
    ["airport_long", 79, 6, byLabel.Home, byLabel.Airport, "xl", "AIRPORT10", 5, "Airport pickup instructions were clear."],
    ["mall_home", 82, 17, byLabel.Mall, byLabel.Home, "standard", "", null, "", { unrated: true }],
    ["school_home", 85, 15, byLabel.School, byLabel.Home, "green", "", 5, "Good electric car."],
    ["friend_gym", 88, 10, byLabel["Friend's place"], byLabel.Gym, "standard", "", 4, "Simple trip."],
    ["home_restaurant", 90, 19, byLabel.Home, byLabel["Favorite restaurant"], "plus", "", 5, "Dinner pickup."],
    ["privacy_policy_trip", 12, 8, byLabel.Home, byLabel.Work, "standard", "", 5, "Routine ride."],
    ["invoice_trip", 18, 8, byLabel.Home, byLabel.Work, "standard", "COMMUTE15", 5, "Invoice needed.", { invoice: true }],
    ["refund_trip", 31, 18, byLabel.Work, byLabel.Home, "standard", "", 3, "Fare adjustment requested.", { refund: true, support: "payment issue" }],
    ["late_driver", 7, 18, byLabel.Work, byLabel.Home, "priority", "", 3, "Driver arrived late.", { support: "driver issue" }]
  ];

  const tierMultipliers = { standard: 1, plus: 1.28, priority: 1.45, green: 1.12, xl: 1.65 };
  const promoDiscounts = { COMMUTE15: 2.25, AIRPORT10: 5.5, NIGHT12: 3.25, WEEKEND8: 2.0 };
  const tierTitles = { standard: "Standard", plus: "Plus", priority: "Priority pickup", green: "Green", xl: "XL" };
  const commentsByScore = {
    2: "Reported issue to support.",
    3: "Trip completed but needs improvement.",
    4: "Good ride overall.",
    5: "Great ride."
  };

  const rides = [];
  const payments = [];
  const ratings = [];
  const supportTickets = [];
  const notifications = [];
  const invoices = [];
  const refunds = [];

  scenarios.forEach((scenario, index) => {
    const [key, daysAgo, hour, pickup, destination, tier, promoCode, score, comment, options = {}] = scenario;
    const createdAt = isoDaysAgo(daysAgo, hour, (index * 7) % 55);
    const profile = sfDriverProfiles[index % sfDriverProfiles.length];
    const driver = driverById.get(profile.userId);
    const distance = calculateHaversineDistance(pickup, destination);
    const duration = estimateTripDuration(distance, hour >= 17 && hour <= 19 ? 18 : 24);
    const discount = promoCode ? promoDiscounts[promoCode] || 1.5 : 0;
    const fareBreakdown = {
      ...fareForRide(distance, duration, tierMultipliers[tier] || 1, options.surge || 1, discount),
      promoCode,
      promoTitle: promoCode ? `${promoCode} ride credit` : "",
      rideTier: tier,
      rideTierTitle: tierTitles[tier] || "Standard"
    };
    const status = options.status || "completed";
    const ride = {
      id: `ride_three_month_${key}`,
      riderId: rider.id,
      driverId: status === "cancelled" && options.cancelledBy === "driver" ? profile.userId : profile.userId,
      pickupAddress: pickup.address,
      pickupLatitude: pickup.latitude,
      pickupLongitude: pickup.longitude,
      destinationAddress: destination.address,
      destinationLatitude: destination.latitude,
      destinationLongitude: destination.longitude,
      status,
      rideTier: tier,
      rideTierTitle: tierTitles[tier] || "Standard",
      estimatedDistance: distance,
      estimatedDuration: duration,
      estimatedFare: fareBreakdown.estimatedTotal,
      currencyCode: "USD",
      currencySymbol: "$",
      currencyDecimals: 2,
      finalDistance: status === "completed" ? distance : null,
      finalDuration: status === "completed" ? duration : null,
      finalFare: status === "completed" ? fareBreakdown.estimatedTotal : null,
      fareBreakdown,
      promoCode,
      discountAmount: discount,
      paymentMethod: index % 5 === 0 ? "pm_rider_paypal" : index % 4 === 0 ? "pm_rider_wallet" : "pm_rider_visa",
      paymentStatus: status === "completed" ? "paid" : "cancelled",
      cancellationReason: status === "cancelled" ? (options.cancelledBy === "driver" ? "Driver cancelled before pickup" : "Rider cancelled before pickup") : "",
      rejectedDriverIds: [],
      scheduledFor: "",
      timeline: timelineForRide(status, createdAt, { driverCancelled: options.cancelledBy === "driver" }),
      createdAt,
      acceptedAt: status === "completed" ? new Date(Date.parse(createdAt) + 3 * 60 * 1000).toISOString() : null,
      startedAt: status === "completed" ? new Date(Date.parse(createdAt) + 12 * 60 * 1000).toISOString() : null,
      completedAt: status === "completed" ? new Date(Date.parse(createdAt) + duration * 60 * 1000).toISOString() : null,
      cancelledAt: status === "cancelled" ? new Date(Date.parse(createdAt) + 4 * 60 * 1000).toISOString() : null,
      invoiceStatus: options.invoice ? "issued" : index % 7 === 0 ? "eligible" : "",
      contactedSupport: Boolean(options.support),
      abnormalFlag: Boolean(options.support || options.paymentRetry || options.surge)
    };
    rides.push(ride);

    if (status === "completed") {
      if (options.paymentRetry) {
        payments.push({
          id: `pay_three_month_${key}_failed`,
          rideId: ride.id,
          riderId: rider.id,
          driverId: profile.userId,
          amount: fareBreakdown.estimatedTotal,
          platformFee: 0,
          driverEarnings: 0,
          currencyCode: "USD",
          currencySymbol: "$",
          currencyDecimals: 2,
          paymentMethod: ride.paymentMethod,
          providerPaymentId: `processor_failed_${key}`,
          status: "failed",
          failureReason: "Issuer declined first attempt",
          createdAt: new Date(Date.parse(createdAt) + 27 * 60 * 1000).toISOString()
        });
      }
      const platformFee = Number((fareBreakdown.estimatedTotal * 0.18).toFixed(2));
      payments.push({
        id: `pay_three_month_${key}`,
        rideId: ride.id,
        riderId: rider.id,
        driverId: profile.userId,
        amount: fareBreakdown.estimatedTotal,
        platformFee,
        driverEarnings: Number((fareBreakdown.estimatedTotal - platformFee).toFixed(2)),
        currencyCode: "USD",
        currencySymbol: "$",
        currencyDecimals: 2,
        paymentMethod: ride.paymentMethod,
        providerPaymentId: `processor_${key}`,
        status: "paid",
        createdAt: new Date(Date.parse(createdAt) + 28 * 60 * 1000).toISOString()
      });
      if (score && !options.unrated) {
        ratings.push({
          id: `rating_three_month_${key}`,
          rideId: ride.id,
          fromUserId: rider.id,
          toUserId: profile.userId,
          score,
          comment: comment || commentsByScore[score],
          createdAt: new Date(Date.parse(createdAt) + 45 * 60 * 1000).toISOString()
        });
      }
      if (options.invoice) {
        invoices.push({
          id: `invoice_three_month_${key}`,
          rideId: ride.id,
          userId: rider.id,
          title: "Riley Rider",
          email: rider.email,
          status: "issued",
          amount: fareBreakdown.estimatedTotal,
          createdAt: new Date(Date.parse(createdAt) + 60 * 60 * 1000).toISOString()
        });
      }
      if (options.refund) {
        refunds.push({
          id: `refund_three_month_${key}`,
          rideId: ride.id,
          userId: rider.id,
          amount: 4.25,
          reason: "Fare adjustment after support review",
          status: "approved",
          createdAt: new Date(Date.parse(createdAt) + 2 * 60 * 60 * 1000).toISOString()
        });
      }
    }

    if (options.support) {
      supportTickets.push({
        id: `ticket_three_month_${key}`,
        userId: rider.id,
        rideId: ride.id,
        category: options.support,
        message: `${options.support}: ${comment || "Please review this ride."}`,
        status: options.support === "safety concern" ? "resolved" : "closed",
        createdAt: new Date(Date.parse(createdAt) + 50 * 60 * 1000).toISOString(),
        updatedAt: new Date(Date.parse(createdAt) + 4 * 60 * 60 * 1000).toISOString()
      });
    }

  });
  const userCoupons = [];

  return {
    rides,
    payments,
    ratings,
    supportTickets,
    notifications,
    invoices,
    refunds,
    userCoupons,
    savedPlaces: favoritePlaces.map((place) => ({
      id: place.id,
      userId: rider.id,
      label: place.label,
      address: place.address,
      latitude: place.latitude,
      longitude: place.longitude,
      lastUsedAt: place.lastUsedAt,
      usageCount: place.usageCount,
      pinned: place.pinned,
      createdAt: isoDaysAgo(89, 9),
      updatedAt: place.lastUsedAt
    }))
  };
}

function createSeedData() {
  const createdAt = now();
  const rider = user("usr_rider_primary", "Riley Rider", "rider@example.com", "+1555010101", "rider");
  const rider2 = user("usr_rider_second", "Jordan Lee", "rider2@example.com", "+1555010102", "rider");
  const rider3 = user("usr_rider_third", "Ava Chen", "rider3@example.com", "+1555010301", "rider");
  const driver = user("usr_driver_primary", "Maya Rodriguez", "driver@example.com", "+13235550147", "driver");
  const driver2 = user("usr_driver_second", "Owen Patel", "driver2@example.com", "+12135550182", "driver");
  const driver3 = user("usr_driver_third", "Elena Park", "driver3@example.com", "+1555031001", "driver");
  const pending = user("usr_driver_pending", "Nora Pending", "pending-driver@example.com", "+1555020203", "driver");
  const admin = user("usr_admin_primary", "Ops Admin", "admin@example.com", "+1555090909", "admin");
  const networkDrivers = [
    user("usr_driver_nyc", "Avery NYC", "nyc-driver@example.com", "+1555030001", "driver"),
    user("usr_driver_chicago", "Sam Chicago", "chicago-driver@example.com", "+1555030002", "driver"),
    user("usr_driver_sf", "Casey Bay", "sf-driver@example.com", "+1555030003", "driver"),
    user("usr_driver_dc", "Morgan DC", "dc-driver@example.com", "+1555030004", "driver"),
    user("usr_driver_dallas", "Quinn Dallas", "dallas-driver@example.com", "+1555030007", "driver")
  ];
  const manualNetworkDriverCityIds = new Set([
    "los_angeles",
    "new_york",
    "chicago",
    "sf_bay",
    "washington_dc",
    "dallas"
  ]);
  const globalDriverCities = serviceCities.filter((city) => !manualNetworkDriverCityIds.has(city.id));
  const globalNetworkDrivers = globalDriverCities.map((city, index) =>
    user(
      `usr_driver_${city.id}`,
      `${city.name} Driver`,
      `${city.id.replaceAll("_", "-")}-driver@example.com`,
      `+155504${String(index + 1).padStart(4, "0")}`,
      "driver"
    )
  );

  const completedRide = {
    id: "ride_seed_completed",
    riderId: rider2.id,
    driverId: driver2.id,
    pickupAddress: locations.times_square.address,
    pickupLatitude: locations.times_square.latitude,
    pickupLongitude: locations.times_square.longitude,
    destinationAddress: locations.nyu.address,
    destinationLatitude: locations.nyu.latitude,
    destinationLongitude: locations.nyu.longitude,
    status: "completed",
    estimatedDistance: 3.3,
    estimatedDuration: 15,
    estimatedFare: 17.36,
    currencyCode: "USD",
    currencySymbol: "$",
    currencyDecimals: 2,
    finalDistance: 3.3,
    finalDuration: 15,
    finalFare: 17.36,
    fareBreakdown: { baseFare: 4.5, distanceFare: 6.11, timeFare: 4.8, serviceFee: 1.75, surgeMultiplier: 1, estimatedTotal: 17.36 },
    paymentMethod: "card_on_file",
    paymentStatus: "paid",
    cancellationReason: "",
    rejectedDriverIds: [],
    timeline: [
      { status: "requested", label: "Ride requested", at: createdAt },
      { status: "searching", label: "Searching for a driver", at: createdAt },
      { status: "accepted", label: "Driver accepted", at: createdAt },
      { status: "driver_arriving", label: "Driver en route", at: createdAt },
      { status: "arrived", label: "Driver arrived", at: createdAt },
      { status: "in_progress", label: "Trip started", at: createdAt },
      { status: "completed", label: "Trip completed", at: createdAt }
    ],
    createdAt,
    acceptedAt: createdAt,
    startedAt: createdAt,
    completedAt: createdAt,
    cancelledAt: null
  };

  const driverProfiles = [
      driverProfile({
        id: "drv_profile_primary",
        userId: driver.id,
        licenseNumber: "NY-DL-100492",
        vehicleMake: "Tesla",
        vehicleModel: "Model Y",
        vehicleYear: 2023,
        licensePlate: "8XJR214",
        vehicleColor: "Pearl White",
        verificationStatus: "approved",
        driverStatus: "online",
        currentLatitude: 34.0646,
        currentLongitude: -118.2379,
        averageRating: 4.92,
        totalTrips: 128,
        createdAt
      }),
      driverProfile({
        id: "drv_profile_second",
        userId: driver2.id,
        licenseNumber: "NY-DL-204882",
        vehicleMake: "Hyundai",
        vehicleModel: "Ioniq 5",
        vehicleYear: 2023,
        licensePlate: "NYC-2048",
        vehicleColor: "Midnight Black",
        verificationStatus: "approved",
        driverStatus: "online",
        currentLatitude: 40.7549,
        currentLongitude: -73.9840,
        averageRating: 4.87,
        totalTrips: 94,
        createdAt
      }),
      driverProfile({
        id: "drv_profile_pending",
        userId: pending.id,
        licenseNumber: "",
        vehicleMake: "Tesla",
        vehicleModel: "Model 3",
        vehicleYear: 2023,
        licensePlate: "EV-2094",
        vehicleColor: "Blue",
        verificationStatus: "pending",
        driverStatus: "offline",
        currentLatitude: 34.0207,
        currentLongitude: -118.2854,
        averageRating: 5,
        totalTrips: 0,
        createdAt
      }),
      driverProfile({
        id: "drv_profile_third",
        userId: driver3.id,
        licenseNumber: "WA-DL-778210",
        vehicleMake: "Rivian",
        vehicleModel: "R1S",
        vehicleYear: 2024,
        licensePlate: "SEA-7782",
        vehicleColor: "Forest Green",
        verificationStatus: "approved",
        driverStatus: "online",
        currentLatitude: 47.6110,
        currentLongitude: -122.3370,
        averageRating: 4.98,
        totalTrips: 243,
        createdAt
      }),
      driverProfile({ id: "drv_profile_nyc", userId: "usr_driver_nyc", licenseNumber: "NY-DL-304812", vehicleMake: "Hyundai", vehicleModel: "Ioniq 5", vehicleYear: 2023, licensePlate: "NYC-8104", vehicleColor: "White", currentLatitude: 40.7549, currentLongitude: -73.9840, averageRating: 4.96, totalTrips: 212, createdAt }),
      driverProfile({ id: "drv_profile_chicago", userId: "usr_driver_chicago", licenseNumber: "IL-DL-540122", vehicleMake: "Toyota", vehicleModel: "RAV4", vehicleYear: 2022, licensePlate: "CHI-5127", vehicleColor: "Blue", currentLatitude: 41.8836, currentLongitude: -87.6320, averageRating: 4.89, totalTrips: 166, createdAt }),
      driverProfile({ id: "drv_profile_sf", userId: "usr_driver_sf", licenseNumber: "CA-DL-782014", vehicleMake: "Tesla", vehicleModel: "Model Y", vehicleYear: 2023, licensePlate: "BAY-6049", vehicleColor: "Red", currentLatitude: 37.7890, currentLongitude: -122.4010, averageRating: 4.94, totalTrips: 198, createdAt }),
      driverProfile({ id: "drv_profile_dc", userId: "usr_driver_dc", licenseNumber: "DC-DL-140822", vehicleMake: "Honda", vehicleModel: "CR-V", vehicleYear: 2021, licensePlate: "DC-2481", vehicleColor: "Gray", currentLatitude: 38.8974, currentLongitude: -77.0320, averageRating: 4.91, totalTrips: 142, createdAt }),
      driverProfile({ id: "drv_profile_dallas", userId: "usr_driver_dallas", licenseNumber: "TX-DL-391804", vehicleMake: "Ford", vehicleModel: "Escape", vehicleYear: 2022, licensePlate: "DFW-6620", vehicleColor: "Silver", currentLatitude: 32.7810, currentLongitude: -96.7990, averageRating: 4.86, totalTrips: 119, createdAt }),
      ...globalDriverCities.map((city, index) =>
        driverProfile({
          id: `drv_profile_${city.id}`,
          userId: `usr_driver_${city.id}`,
          licenseNumber: `GL-${String(index + 1).padStart(5, "0")}`,
          vehicleMake: ["Toyota", "Hyundai", "Tesla", "Honda", "Kia", "Nissan"][index % 6],
          vehicleModel: ["Camry", "Ioniq 5", "Model Y", "CR-V", "Telluride", "Altima"][index % 6],
          vehicleYear: 2021 + (index % 3),
          licensePlate: city.id.slice(0, 3).toUpperCase().padEnd(3, "X") + `-${String(4100 + index)}`,
          vehicleColor: ["White", "Black", "Silver", "Blue", "Gray"][index % 5],
          currentLatitude: Number((city.centerLatitude + 0.012).toFixed(6)),
          currentLongitude: Number((city.centerLongitude - 0.012).toFixed(6)),
          averageRating: Number((4.85 + (index % 10) * 0.01).toFixed(2)),
          totalTrips: 80 + index * 7,
          createdAt
        })
      )
    ];
  const riderExperience = buildThreeMonthRiderExperience({
    rider,
    drivers: [driver, driver2, driver3, ...networkDrivers, ...globalNetworkDrivers],
    driverProfiles
  });
  const extraSavedPlaces = [
    { id: "place_rider_second_home", userId: rider2.id, label: "Home", address: "Upper West Side, New York, NY", latitude: 40.7870, longitude: -73.9754, usageCount: 12, pinned: true, createdAt: isoDaysAgo(28, 8), updatedAt: isoDaysAgo(1, 18) },
    { id: "place_rider_second_work", userId: rider2.id, label: "Work", address: locations.times_square.address, latitude: locations.times_square.latitude, longitude: locations.times_square.longitude, usageCount: 16, pinned: true, createdAt: isoDaysAgo(28, 8), updatedAt: isoDaysAgo(2, 8) },
    { id: "place_rider_second_grocery", userId: rider2.id, label: "Grocery", address: "Chelsea Market, New York, NY", latitude: 40.7424, longitude: -74.0060, usageCount: 5, pinned: false, createdAt: isoDaysAgo(18, 12), updatedAt: isoDaysAgo(3, 17) },
    { id: "place_rider_third_home", userId: rider3.id, label: "Home", address: "Capitol Hill, Seattle, WA", latitude: 47.6253, longitude: -122.3222, usageCount: 10, pinned: true, createdAt: isoDaysAgo(21, 8), updatedAt: isoDaysAgo(1, 19) },
    { id: "place_rider_third_work", userId: rider3.id, label: "Work", address: locations.downtown_seattle.address, latitude: locations.downtown_seattle.latitude, longitude: locations.downtown_seattle.longitude, usageCount: 14, pinned: true, createdAt: isoDaysAgo(21, 8), updatedAt: isoDaysAgo(2, 9) },
    { id: "place_rider_third_pharmacy", userId: rider3.id, label: "Pharmacy", address: "CVS Pharmacy, Seattle, WA", latitude: 47.6097, longitude: -122.3331, usageCount: 3, pinned: false, createdAt: isoDaysAgo(14, 12), updatedAt: isoDaysAgo(4, 16) }
  ];
  const extraUserCoupons = [
    { id: "coupon_rider_second_commute", userId: rider2.id, code: "COMMUTE15", title: "15% off commute rides", percentOff: 15, amountOff: 0, status: "available", createdAt, expiresAt: new Date(Date.parse(createdAt) + 21 * 24 * 60 * 60 * 1000).toISOString() },
    { id: "coupon_rider_third_airport", userId: rider3.id, code: "AIRPORT10", title: "10% off airport rides", percentOff: 10, amountOff: 0, status: "available", createdAt, expiresAt: new Date(Date.parse(createdAt) + 30 * 24 * 60 * 60 * 1000).toISOString() }
  ];

  return {
    meta: {
      appName: "opendriver",
      schemaVersion: 16,
      city: { name: "Global Service Network", centerLatitude: 20.0, centerLongitude: 0.0 },
      serviceCityIds: serviceCities.map((city) => city.id),
      seededAt: createdAt
    },
    users: [rider, rider2, rider3, driver, driver2, driver3, pending, admin, ...networkDrivers, ...globalNetworkDrivers],
    driverProfiles,
    rides: [...riderExperience.rides, completedRide],
    paymentMethods: [
      { id: "pm_rider_visa", userId: rider.id, type: "card", brand: "Visa", label: "Visa ending 4242", last4: "4242", isDefault: true, status: "active", createdAt },
      { id: "pm_rider_wallet", userId: rider.id, type: "wallet", brand: "Ride Cash", label: "Ride Cash balance", last4: "", isDefault: false, status: "active", createdAt },
      { id: "pm_rider_paypal", userId: rider.id, type: "paypal", brand: "PayPal", label: "PayPal rider@example.com", last4: "", isDefault: false, status: "active", createdAt },
      { id: "pm_rider_backup", userId: rider.id, type: "card", brand: "Mastercard", label: "Mastercard ending 9001", last4: "9001", isDefault: false, status: "active", createdAt },
      { id: "pm_rider_second_paypal", userId: rider2.id, type: "paypal", brand: "PayPal", label: "PayPal rider2@example.com", last4: "", isDefault: true, status: "active", createdAt },
      { id: "pm_rider_second_visa", userId: rider2.id, type: "card", brand: "Visa", label: "Visa ending 3188", last4: "3188", isDefault: false, status: "active", createdAt },
      { id: "pm_rider_third_amex", userId: rider3.id, type: "card", brand: "Amex", label: "Amex ending 1005", last4: "1005", isDefault: true, status: "active", createdAt },
      { id: "pm_rider_third_wallet", userId: rider3.id, type: "wallet", brand: "Ride Cash", label: "Ride Cash balance", last4: "", isDefault: false, status: "active", createdAt },
      { id: "pm_driver_primary", userId: driver.id, type: "card", brand: "Visa", label: "Visa ending 1881", last4: "1881", isDefault: true, status: "active", createdAt }
    ],
    savedPlaces: [...riderExperience.savedPlaces, ...extraSavedPlaces],
    promotions: [
      { code: "WELCOME20", title: "20% off your next ride", percentOff: 20, active: true, createdAt },
      { code: "AIRPORT10", title: "10% off airport rides", percentOff: 10, active: true, createdAt },
      { code: "COMMUTE15", title: "15% off commute rides", percentOff: 15, active: true, createdAt },
      { code: "NIGHT12", title: "12% off late-night rides", percentOff: 12, active: true, createdAt },
      { code: "WEEKEND8", title: "Weekend ride credit", percentOff: 8, active: true, createdAt },
      { code: "SAVE3", title: "$3 ride credit", amountOff: 3, active: true, createdAt },
      { code: "RIDE6", title: "$6 off your next ride", amountOff: 6, active: true, createdAt },
      { code: "BIG10", title: "$10 premium ride credit", amountOff: 10, active: true, createdAt }
    ],
    userCoupons: [...riderExperience.userCoupons, ...extraUserCoupons],
    payments: [
      ...riderExperience.payments,
      {
        id: "pay_seed_completed",
        rideId: completedRide.id,
        riderId: completedRide.riderId,
        driverId: completedRide.driverId,
        amount: 13.52,
        platformFee: 2.43,
        driverEarnings: 11.09,
        currencyCode: "USD",
        currencySymbol: "$",
        currencyDecimals: 2,
        paymentMethod: "card_on_file",
        providerPaymentId: "processor_seed",
        status: "paid",
        createdAt
      }
    ],
    ratings: [
      ...riderExperience.ratings,
      { id: "rating_seed", rideId: completedRide.id, fromUserId: rider2.id, toUserId: driver.id, score: 5, comment: "Great pickup.", createdAt }
    ],
    supportTickets: [
      ...riderExperience.supportTickets,
      { id: "ticket_seed", userId: rider2.id, rideId: completedRide.id, category: "payment issue", message: "Please send receipt copy.", status: "open", createdAt, updatedAt: createdAt }
    ],
    notifications: riderExperience.notifications,
    invoices: riderExperience.invoices,
    refunds: riderExperience.refunds,
    sessions: []
  };
}

module.exports = { sharedPassword, serviceCities, locations, createSeedData };
