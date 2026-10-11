const assert = require("assert");
const domain = require("../src/domain");
const { createSeedData, serviceCities, locations } = require("../src/database/seed");

const distance = domain.calculateHaversineDistance(
  { latitude: 40.758, longitude: -73.9855 },
  { latitude: 40.7411, longitude: -73.9897 }
);
assert(distance > 1.8 && distance < 2.3, `distance=${distance}`);

const duration = domain.estimateTripDuration(distance);
assert(duration >= 5);

const fare = domain.estimateFare({ distanceKm: distance, durationMinutes: duration, availableDrivers: 3 });
assert(fare.estimatedTotal >= 8);
const daytimeFare = domain.estimateFare({
  distanceKm: 12,
  durationMinutes: 34,
  availableDrivers: 3,
  pickupTime: "2026-06-10T12:00:00"
});
const morningPeakFare = domain.estimateFare({
  distanceKm: 12,
  durationMinutes: 34,
  availableDrivers: 3,
  pickupTime: "2026-06-10T08:00:00"
});
assert(morningPeakFare.estimatedTotal > daytimeFare.estimatedTotal);
assert(morningPeakFare.pickupTimeAdjustment > daytimeFare.pickupTimeAdjustment);

assert.strictEqual(domain.validateTransition("searching", "accepted").ok, true);
assert.strictEqual(domain.validateTransition("arrived", "completed").ok, false);
assert.strictEqual(domain.validateTransition("completed", "cancelled").ok, false);

const db = createSeedData();
assert.strictEqual(serviceCities.length, 20, `serviceCities=${serviceCities.length}`);
assert(Object.keys(locations).length >= 140, `locations=${Object.keys(locations).length}`);
assert(serviceCities.some((city) => city.id === "ann_arbor"));
assert(serviceCities.some((city) => city.id === "aurora_il"));
assert(serviceCities.some((city) => city.id === "arlington_va"));
assert(serviceCities.some((city) => city.id === "seattle"));
assert(!serviceCities.some((city) => city.id === "alexandria_va"));
assert(!serviceCities.some((city) => city.id === "miami"));
assert.strictEqual(db.meta.schemaVersion, 16);
assert.strictEqual(db.users.filter((item) => item.role === "rider").length, 3);
assert.strictEqual(
  db.users.filter((item) => ["driver@example.com", "driver2@example.com", "driver3@example.com"].includes(item.email)).length,
  3
);
assert(db.users.some((item) => item.email === "rider3@example.com" && item.role === "rider"));
assert(db.users.some((item) => item.email === "driver3@example.com" && item.role === "driver"));
assert(!db.users.some((item) => item.email === "rider4@example.com"));
assert(!db.users.some((item) => item.email === "driver4@example.com"));
assert(db.paymentMethods.some((item) => item.userId === "usr_rider_second" && item.type === "paypal" && item.isDefault));
assert(db.paymentMethods.some((item) => item.userId === "usr_rider_third" && item.brand === "Amex" && item.isDefault));
assert(db.savedPlaces.some((item) => item.userId === "usr_rider_second" && item.label === "Home" && item.address.includes("New York")));
assert(db.savedPlaces.some((item) => item.userId === "usr_rider_third" && item.label === "Pharmacy"));
assert(db.savedPlaces.some((item) => item.userId === "usr_rider_third" && item.label === "Home" && item.address.includes("Seattle")));
assert(db.driverProfiles.some((item) => item.userId === "usr_driver_second" && item.currentLatitude > 40 && item.currentLongitude < -73));
assert(db.driverProfiles.some((item) => item.userId === "usr_driver_third" && item.vehicleMake === "Rivian" && item.currentLatitude > 47));
assert(!db.driverProfiles.some((profile) => profile.userId === "usr_driver_london"));
assert(!db.driverProfiles.some((profile) => profile.userId === "usr_driver_tokyo"));
const manualDriverUsersByCity = {
  los_angeles: "usr_driver_primary",
  new_york: "usr_driver_nyc",
  chicago: "usr_driver_chicago",
  sf_bay: "usr_driver_sf",
  washington_dc: "usr_driver_dc",
  dallas: "usr_driver_dallas"
};
for (const city of serviceCities) {
  const userId = manualDriverUsersByCity[city.id] || `usr_driver_${city.id}`;
  assert(db.driverProfiles.some((profile) => profile.userId === userId), `${city.id} has no seeded driver`);
}
for (const profile of db.driverProfiles) {
  const insideSupportedCity = serviceCities.some((city) => {
    const distanceKm = domain.calculateHaversineDistance(
      { latitude: city.centerLatitude, longitude: city.centerLongitude },
      { latitude: profile.currentLatitude, longitude: profile.currentLongitude }
    );
    return distanceKm <= city.radiusKm;
  });
  assert(insideSupportedCity, `${profile.userId} is outside supported driver service cities`);
}
assert.strictEqual(db.notifications.filter((item) => item.userId === "usr_rider_primary").length, 0);
assert.strictEqual(db.userCoupons.filter((item) => item.userId === "usr_rider_primary").length, 0);
const drivers = domain.nearbyDrivers(db, { pickupLatitude: 40.758, pickupLongitude: -73.9855, rejectedDriverIds: [] });
assert(drivers.length >= 1);
assert.strictEqual(drivers[0].profile.verificationStatus, "approved");

const ride = {
  id: "ride_test",
  riderId: "usr_rider_primary",
  driverId: "usr_driver_primary",
  estimatedFare: 20,
  finalFare: 20,
  paymentMethod: "card_on_file"
};
const payment = domain.createPaymentRecord(db, ride);
assert.strictEqual(payment.status, "paid");
assert(payment.driverEarnings > payment.platformFee);

console.log("backend domain tests passed");
