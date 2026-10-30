const fs = require("fs");

const rootUsername = process.env.MONGO_INITDB_ROOT_USERNAME || "mongo_root";
const appDatabase = process.env.MONGO_APP_DATABASE || "mechanics_agent";
const appUsername = process.env.MONGO_APP_USERNAME || "mechanics_app";

const rootPassword = fs
  .readFileSync("/run/secrets/mongo_root_password", "utf8")
  .trim();
const appPassword = fs
  .readFileSync("/run/secrets/mongo_app_password", "utf8")
  .trim();

if (!rootPassword || !appPassword) {
  throw new Error("MongoDB recovery secrets must not be empty");
}

function upsertUser(database, username, password, roles) {
  const users = database.getUsers().users || [];
  if (users.some((user) => user.user === username)) {
    database.updateUser(username, { pwd: password, roles });
    return "updated";
  }
  database.createUser({ user: username, pwd: password, roles });
  return "created";
}

const adminDatabase = db.getSiblingDB("admin");
const rootAction = upsertUser(adminDatabase, rootUsername, rootPassword, [
  { role: "root", db: "admin" },
]);

const applicationDatabase = db.getSiblingDB(appDatabase);
const appAction = upsertUser(
  applicationDatabase,
  appUsername,
  appPassword,
  [{ role: "readWrite", db: appDatabase }],
);

if (!applicationDatabase.getCollectionNames().includes("deployment_audit")) {
  applicationDatabase.createCollection("deployment_audit");
}
applicationDatabase.deployment_audit.createIndex({ created_at: 1 });

printjson({
  ok: 1,
  root_user: rootUsername,
  root_action: rootAction,
  app_database: appDatabase,
  app_user: appUsername,
  app_action: appAction,
});
