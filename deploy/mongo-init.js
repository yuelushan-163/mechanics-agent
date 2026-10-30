const fs = require("fs");

const databaseName = process.env.MONGO_APP_DATABASE || "mechanics_agent";
const username = process.env.MONGO_APP_USERNAME || "mechanics_app";
const password = fs.readFileSync("/run/secrets/mongo_app_password", "utf8").trim();

if (!password) {
  throw new Error("MongoDB application password is empty");
}

const applicationDatabase = db.getSiblingDB(databaseName);
applicationDatabase.createUser({
  user: username,
  pwd: password,
  roles: [{ role: "readWrite", db: databaseName }],
});

const collections = [
  "deployment_audit",
  "users",
  "projects",
  "tasks",
  "approvals",
  "error_logs",
];

for (const collection of collections) {
  if (!applicationDatabase.getCollectionNames().includes(collection)) {
    applicationDatabase.createCollection(collection);
  }
}

applicationDatabase.deployment_audit.createIndex({ created_at: 1 });
applicationDatabase.users.createIndex({ user_id: 1 }, { unique: true });
applicationDatabase.users.createIndex({ email: 1 }, { unique: true, sparse: true });
applicationDatabase.projects.createIndex({ project_id: 1 }, { unique: true });
applicationDatabase.projects.createIndex({ owner_user_id: 1, updated_at: -1 });
applicationDatabase.tasks.createIndex({ task_id: 1 }, { unique: true });
applicationDatabase.tasks.createIndex({ project_id: 1, status: 1 });
applicationDatabase.approvals.createIndex({ approval_id: 1 }, { unique: true });
applicationDatabase.approvals.createIndex({ task_id: 1, decision: 1 });
applicationDatabase.error_logs.createIndex({ timestamp: -1 });
applicationDatabase.error_logs.createIndex({ request_id: 1 });
applicationDatabase.error_logs.createIndex({ level: 1, timestamp: -1 });
