const crypto = require("crypto");

const rideStatuses = [
  "scheduled",
  "requested",
  "searching",
  "accepted",
  "driver_arriving",
  "arrived",
  "in_progress",
  "completed",
  "cancelled"
];

const allowedTransitions = {
  scheduled: ["searching", "cancelled"],
  requested: ["searching", "cancelled"],
  searching: ["accepted", "cancelled"],
  accepted: ["driver_arriving", "cancelled"],
  driver_arriving: ["arrived"],
  arrived: ["in_progress"],
  in_progress: ["completed"],
  completed: [],
  cancelled: []
};

function now() {
  return new Date().toISOString();
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function makeId(prefix) {
  return `${prefix}_${crypto.randomBytes(8).toString("hex")}`;
}

function hashPassword(password, salt = crypto.randomBytes(16).toString("hex")) {
  const hash = crypto.pbkdf2Sync(String(password), salt, 120000, 32, "sha256").toString("hex");
  return `pbkdf2$${salt}$${hash}`;
}

function verifyPassword(password, passwordHash) {
  const [scheme, salt] = String(passwordHash || "").split("$");
  if (scheme !== "pbkdf2" || !salt) return false;
  return hashPassword(password, salt) === passwordHash;
}

function createToken() {
  return crypto.randomBytes(32).toString("hex");
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function normalizeNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeLocation(input) {
  const latitude = normalizeNumber(input?.latitude ?? input?.lat);
  const longitude = normalizeNumber(input?.longitude ?? input?.lng);
  if (latitude === null || longitude === null) return null;
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;
  return { latitude, longitude };
}

function toRadians(value) {
  return (Number(value) * Math.PI) / 180;
}

function calculateHaversineDistance(a, b) {
  const start = normalizeLocation(a);
  const end = normalizeLocation(b);
  if (!start || !end) return 0;
  const earthKm = 6371;
  const dLat = toRadians(end.latitude - start.latitude);
  const dLng = toRadians(end.longitude - start.longitude);
  const lat1 = toRadians(start.latitude);
  const lat2 = toRadians(end.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return Number((2 * earthKm * Math.asin(Math.sqrt(h))).toFixed(2));
}

function estimateTripDuration(distanceKm, averageSpeedKph = 24) {
  return Math.max(5, Math.ceil((Math.max(distanceKm, 0.6) / averageSpeedKph) * 60 + 4));
}

function roundMoney(value) {
  return Number(Number(value || 0).toFixed(2));
}

function pickupTimePricing(pickupTime) {
  const parsedTime = pickupTime ? Date.parse(pickupTime) : Date.now();
  const date = new Date(Number.isFinite(parsedTime) ? parsedTime : Date.now());
  const minutes = date.getHours() * 60 + date.getMinutes();
  if (minutes < 60) return { multiplier: 1.1, label: "Late night" };
  if (minutes < 240) return { multiplier: 1.06, label: "Overnight" };
  if (minutes < 420) return { multiplier: 0.96, label: "Early morning" };
  if (minutes < 570) return { multiplier: 1.22, label: "Morning peak" };
  if (minutes < 930) return { multiplier: 1, label: "Daytime" };
  if (minutes < 1140) return { multiplier: 1.28, label: "Evening peak" };
  if (minutes < 1320) return { multiplier: 1.1, label: "Evening" };
  return { multiplier: 1.16, label: "Late evening" };
}

function estimateFare({ distanceKm, durationMinutes, availableDrivers = 2, pickupTime = null, waypointCount = 0 }) {
  const baseFare = 4.5;
  const distanceFare = Number((Math.max(distanceKm, 0.6) * 1.85).toFixed(2));
  const timeFare = Number((Math.max(durationMinutes, 5) * 0.32).toFixed(2));
  const serviceFee = 1.75;
  const waypointFee = Number((Math.max(0, Number(waypointCount) || 0) * 1.5).toFixed(2));
  const surgeMultiplier = availableDrivers < 2 ? 1.18 : 1;
  const timePricing = pickupTimePricing(pickupTime);
  const subtotal = baseFare + distanceFare + timeFare + serviceFee + waypointFee;
  const driverAdjustedSubtotal = roundMoney(subtotal * surgeMultiplier);
  const pickupTimeAdjustment = roundMoney(driverAdjustedSubtotal * (timePricing.multiplier - 1));
  const estimatedTotal = roundMoney(Math.max(8, driverAdjustedSubtotal + pickupTimeAdjustment));
  return {
    baseFare,
    distanceFare,
    timeFare,
    serviceFee,
    waypointFee,
    surgeMultiplier,
    pickupTimeMultiplier: timePricing.multiplier,
    pickupTimeLabel: timePricing.label,
    pickupTimeAdjustment,
    estimatedTotal
  };
}

function canTransition(from, to) {
  return Boolean(allowedTransitions[from]?.includes(to));
}

function validateTransition(from, to) {
  if (!rideStatuses.includes(to)) {
    return { ok: false, code: "INVALID_RIDE_STATUS", message: "Unsupported ride status." };
  }
  if (!canTransition(from, to)) {
    return { ok: false, code: "INVALID_RIDE_TRANSITION", message: `Cannot move ride from ${from} to ${to}.` };
  }
  return { ok: true };
}

function publicUser(user) {
  if (!user) return null;
  const safe = clone(user);
  delete safe.passwordHash;
  delete safe.sharedPassword;
  return safe;
}

function publicDriver(db, profile) {
  if (!profile) return null;
  const documents = Array.isArray(profile.documents) ? profile.documents : [];
  const requiredTypes = ["license", "insurance", "vehicle_inspection"];
  const approved = requiredTypes.filter((type) => documents.some((doc) => doc.type === type && doc.status === "approved"));
  return {
    ...clone(profile),
    documents,
    documentSummary: {
      required: requiredTypes.length,
      submitted: requiredTypes.filter((type) => documents.some((doc) => doc.type === type)).length,
      approved: approved.length,
      status: approved.length === requiredTypes.length ? "complete" : documents.length > 0 ? "in_review" : "missing"
    },
    user: publicUser(db.users.find((user) => user.id === profile.userId))
  };
}

function publicRide(db, ride) {
  if (!ride) return null;
  const driverProfile = ride.driverId ? db.driverProfiles.find((item) => item.userId === ride.driverId) : null;
  const showDriver = driverProfile && ["accepted", "driver_arriving", "arrived", "in_progress", "completed"].includes(ride.status);
  const driverDistanceToPickupKm = driverProfile
    ? calculateHaversineDistance(
        { latitude: driverProfile.currentLatitude, longitude: driverProfile.currentLongitude },
        { latitude: ride.pickupLatitude, longitude: ride.pickupLongitude }
      )
    : null;
  const driverDistanceToDestinationKm = driverProfile
    ? calculateHaversineDistance(
        { latitude: driverProfile.currentLatitude, longitude: driverProfile.currentLongitude },
        { latitude: ride.destinationLatitude, longitude: ride.destinationLongitude }
      )
    : null;
  return {
    ...clone(ride),
    driverDistanceToPickupKm,
    driverDistanceToDestinationKm,
    rider: publicUser(db.users.find((user) => user.id === ride.riderId)),
    driver: showDriver ? publicUser(db.users.find((user) => user.id === ride.driverId)) : null,
    driverProfile: showDriver ? publicDriver(db, driverProfile) : null,
    payment: db.payments.find((payment) => payment.rideId === ride.id) || null,
    ratings: db.ratings.filter((rating) => rating.rideId === ride.id)
  };
}

function nearbyDrivers(db, ride) {
  const rejected = ride.rejectedDriverIds || [];
  return db.driverProfiles
    .filter((profile) => {
      return (
        profile.verificationStatus === "approved" &&
        profile.driverStatus === "online" &&
        !rejected.includes(profile.userId)
      );
    })
    .map((profile) => ({
      profile,
      user: db.users.find((user) => user.id === profile.userId),
      distanceKm: calculateHaversineDistance(
        { latitude: profile.currentLatitude, longitude: profile.currentLongitude },
        { latitude: ride.pickupLatitude, longitude: ride.pickupLongitude }
      )
    }))
    .sort((a, b) => a.distanceKm - b.distanceKm || b.profile.averageRating - a.profile.averageRating);
}

function createNotification(db, userId, type, title, message) {
  const notification = { id: makeId("notif"), userId, type, title, message, read: false, createdAt: now() };
  db.notifications.unshift(notification);
  return notification;
}

function createPaymentRecord(db, ride) {
  let payment = db.payments.find((item) => item.rideId === ride.id);
  if (payment) return payment;
  const currencyDecimals = ride.currencyDecimals ?? ride.fareBreakdown?.currencyDecimals ?? 2;
  const amount = Number((ride.finalFare || ride.estimatedFare || 0).toFixed(currencyDecimals));
  const platformFee = Number((amount * 0.18).toFixed(currencyDecimals));
  payment = {
    id: makeId("pay"),
    rideId: ride.id,
    riderId: ride.riderId,
    driverId: ride.driverId,
    amount,
    platformFee,
    driverEarnings: Number((amount - platformFee).toFixed(currencyDecimals)),
    currencyCode: ride.currencyCode || ride.fareBreakdown?.currencyCode || "USD",
    currencySymbol: ride.currencySymbol || ride.fareBreakdown?.currencySymbol || "$",
    currencyDecimals,
    paymentMethod: ride.paymentMethod || "card_on_file",
    providerPaymentId: `processor_${makeId("provider")}`,
    status: "paid",
    createdAt: now()
  };
  db.payments.unshift(payment);
  ride.paymentStatus = "paid";
  return payment;
}

module.exports = {
  rideStatuses,
  allowedTransitions,
  now,
  clone,
  makeId,
  hashPassword,
  verifyPassword,
  createToken,
  normalizeEmail,
  normalizeLocation,
  calculateHaversineDistance,
  estimateTripDuration,
  pickupTimePricing,
  estimateFare,
  validateTransition,
  publicUser,
  publicDriver,
  publicRide,
  nearbyDrivers,
  createNotification,
  createPaymentRecord
};
