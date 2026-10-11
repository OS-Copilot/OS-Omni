const fs = require("fs");
const path = require("path");
const { createSeedData } = require("./seed");

const DATA_DIR = path.join(__dirname, "..", "..", "data");
const DB_PATH = path.join(DATA_DIR, "opendriver-db.json");

function ensureDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

function loadDb() {
  ensureDir();
  if (!fs.existsSync(DB_PATH)) {
    return resetDb();
  }
  const db = JSON.parse(fs.readFileSync(DB_PATH, "utf8"));
  if (!db.meta || Number(db.meta.schemaVersion || 0) < 16) {
    return resetDb();
  }
  return db;
}

function saveDb(db) {
  ensureDir();
  fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2), "utf8");
}

function resetDb() {
  const db = createSeedData();
  saveDb(db);
  return db;
}

module.exports = { DATA_DIR, DB_PATH, loadDb, saveDb, resetDb };
