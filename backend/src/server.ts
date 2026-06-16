import cookieParser from "cookie-parser";
import cors from "cors";
import dotenv from "dotenv";
import express, { type NextFunction, type Request, type Response } from "express";
import { DateTime } from "luxon";
import { MongoClient, type Db, type Document, type Filter } from "mongodb";
import { randomUUID } from "node:crypto";
import { z } from "zod";

dotenv.config();

const MONGO_URL = process.env.MONGO_URL;
const DB_NAME = process.env.DB_NAME;
const PORT = Number(process.env.PORT || 8000);

if (!MONGO_URL) throw new Error("MONGO_URL is required");
if (!DB_NAME) throw new Error("DB_NAME is required");

const client = new MongoClient(MONGO_URL);
let db: Db;

const DETROIT_TZ = "America/Detroit";
const OFFICES = ["MCM", "AMP", "Dearborn", "Heritage", "Siren"] as const;
const LEVELS: Record<Role, string> = {
  level_1: "Agent",
  level_2: "GA",
  level_3: "MGA",
  level_4: "RGA",
};
const EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data";

type Role = "level_1" | "level_2" | "level_3" | "level_4";
type AnyDoc = Record<string, any>;

interface AuthedRequest extends Request {
  user?: AnyDoc;
}

class HttpError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

const asyncHandler =
  (fn: (req: AuthedRequest, res: Response, next: NextFunction) => Promise<unknown>) =>
  (req: AuthedRequest, res: Response, next: NextFunction) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };

const demoLoginSchema = z.object({ level: z.enum(["level_1", "level_2", "level_3", "level_4"]) });
const sessionExchangeSchema = z.object({ session_id: z.string().min(1) });
const pulseSchema = z.object({
  sets: z.coerce.number().int().default(0),
  sits: z.coerce.number().int().default(0),
  sales: z.coerce.number().int().default(0),
  ots_sits: z.coerce.number().int().default(0),
  ots_sales: z.coerce.number().int().default(0),
  n1: z.coerce.number().int().default(0),
  refs_obtained: z.coerce.number().int().default(0),
  ref_sits: z.coerce.number().int().default(0),
  ref_sales: z.coerce.number().int().default(0),
  pos_sits: z.coerce.number().int().default(0),
  pos_sales: z.coerce.number().int().default(0),
  vet_sits: z.coerce.number().int().default(0),
  vet_sales: z.coerce.number().int().default(0),
  gross_alp: z.coerce.number().default(0),
  market: z.string().optional().nullable(),
});
const eraseSchema = z.object({
  agent_id: z.string().min(1),
  sales_day: z.string().min(1),
  new_alp: z.coerce.number(),
  reason: z.string(),
});

function nowUtc(): Date {
  return new Date();
}

function nowDetroit(): DateTime {
  return DateTime.now().setZone(DETROIT_TZ);
}

function salesDayFor(dtLocal: DateTime): string {
  const day = dtLocal.hour < 6 ? dtLocal.minus({ days: 1 }) : dtLocal;
  return day.toISODate()!;
}

function gateState(dtLocal = nowDetroit()) {
  const hour = dtLocal.hour;
  if (hour >= 21 && hour < 24) {
    return {
      state: "warning",
      message: "9:00 PM Deadline Passed. Log your numbers now to avoid leadership escalation.",
      color: "yellow",
    };
  }
  if (hour >= 0 && hour < 6) {
    return {
      state: "midnight_miracle",
      message: "Midnight Miracle window - entries open until 6:00 AM.",
      color: "yellow",
    };
  }
  return { state: "open", message: "Pulse window open.", color: "green" };
}

function currentSalesDayStr(): string {
  return salesDayFor(nowDetroit());
}

function previousSalesDayStr(): string {
  return salesDayFor(nowDetroit().minus({ days: 1 }));
}

function levelNumber(role = "level_1"): number {
  return Number(String(role).split("_")[1] || 1);
}

function omitId<T extends AnyDoc | null>(doc: T): T {
  if (!doc) return doc;
  const { _id, ...rest } = doc;
  return rest as T;
}

function serializeDates<T>(value: T): T {
  if (value instanceof Date) return value.toISOString() as T;
  if (Array.isArray(value)) return value.map(serializeDates) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as AnyDoc)
        .filter(([key]) => key !== "_id")
        .map(([key, val]) => [key, serializeDates(val)]),
    ) as T;
  }
  return value;
}

function sessionTokenFrom(req: Request): string | null {
  const cookieToken = req.cookies?.session_token;
  if (cookieToken) return cookieToken;
  const auth = req.header("authorization");
  if (auth?.toLowerCase().startsWith("bearer ")) return auth.slice(7).trim();
  return null;
}

function setSessionCookie(res: Response, token: string) {
  res.cookie("session_token", token, {
    maxAge: 7 * 24 * 60 * 60 * 1000,
    httpOnly: true,
    secure: true,
    sameSite: "none",
    path: "/",
  });
}

async function getCurrentUser(req: Request): Promise<AnyDoc> {
  const token = sessionTokenFrom(req);
  if (!token) throw new HttpError(401, "Not authenticated");

  const sess = await db.collection("user_sessions").findOne({ session_token: token }, { projection: { _id: 0 } });
  if (!sess) throw new HttpError(401, "Invalid session");

  const expiresAt = sess.expires_at instanceof Date ? sess.expires_at : new Date(sess.expires_at);
  if (expiresAt && expiresAt < nowUtc()) throw new HttpError(401, "Session expired");

  const user = await db.collection("users").findOne({ user_id: sess.user_id }, { projection: { _id: 0 } });
  if (!user) throw new HttpError(401, "User not found");
  return user;
}

const requireAuth = asyncHandler(async (req, _res, next) => {
  req.user = await getCurrentUser(req);
  next();
});

function requireLevel(minLevel: number) {
  return asyncHandler(async (req, _res, next) => {
    const user = await getCurrentUser(req);
    if (levelNumber(user.role) < minLevel) throw new HttpError(403, `Requires level ${minLevel}+`);
    req.user = user;
    next();
  });
}

async function upsertUserAndSession(input: {
  email: string;
  name: string;
  picture?: string | null;
  sessionToken: string;
  role?: Role;
  agentId?: string | null;
}) {
  const role = input.role || "level_1";
  let user: AnyDoc | null = await db.collection("users").findOne({ email: input.email }, { projection: { _id: 0 } });

  if (!user) {
    user = {
      user_id: `user_${randomUUID().replaceAll("-", "").slice(0, 12)}`,
      email: input.email,
      name: input.name,
      picture: input.picture || "",
      role,
      agent_id: input.agentId,
      created_at: nowUtc(),
    };
    await db.collection("users").insertOne(user as AnyDoc);
  } else {
    await db.collection("users").updateOne(
      { user_id: user.user_id },
      {
        $set: {
          name: input.name,
          picture: input.picture || user.picture || "",
          role: user.role || role,
          agent_id: user.agent_id || input.agentId,
        },
      },
    );
    user = await db.collection("users").findOne({ user_id: user.user_id }, { projection: { _id: 0 } });
  }

  await db.collection("user_sessions").insertOne({
    user_id: user!.user_id,
    session_token: input.sessionToken,
    created_at: nowUtc(),
    expires_at: DateTime.utc().plus({ days: 7 }).toJSDate(),
  });
  return omitId(user!);
}

async function visibleAgentIds(user: AnyDoc): Promise<string[] | null> {
  const role = user.role || "level_1";
  if (role === "level_4") return null;
  const agentId = user.agent_id;
  if (!agentId) return [];
  if (role === "level_1") return [agentId];

  const visible = new Set<string>([agentId]);
  let queue = [agentId];
  while (queue.length) {
    const batch = queue;
    queue = [];
    const docs = await db
      .collection("agent_profiles")
      .find({ upline_id: { $in: batch } }, { projection: { _id: 0, agent_id: 1 } })
      .toArray();
    for (const doc of docs) {
      if (!visible.has(doc.agent_id)) {
        visible.add(doc.agent_id);
        queue.push(doc.agent_id);
      }
    }
  }
  return [...visible];
}

async function aggregateAlp(filter: Filter<Document>) {
  const docs = await db
    .collection("production_entries")
    .aggregate([
      { $match: filter },
      {
        $group: {
          _id: null,
          gross_alp: { $sum: "$gross_alp" },
          net_alp: { $sum: "$net_alp" },
          sits: { $sum: "$sits" },
          sales: { $sum: "$sales" },
        },
      },
    ])
    .toArray();

  const doc = docs[0];
  if (!doc) return { gross_alp: 0, net_alp: 0, sits: 0, sales: 0 };
  return {
    gross_alp: Number(doc.gross_alp || 0),
    net_alp: Number(doc.net_alp || 0),
    sits: Number(doc.sits || 0),
    sales: Number(doc.sales || 0),
  };
}

async function maybeTriggerShoutouts(agent: AnyDoc, entry: AnyDoc) {
  const sd = entry.sales_day;
  const agg = await aggregateAlp({ agent_id: agent.agent_id, sales_day: sd });

  if (agg.gross_alp >= 10000) {
    const existing = await db.collection("shoutouts").findOne({
      type: "players_club",
      agent_id: agent.agent_id,
      sales_day: sd,
    });
    if (!existing) {
      await db.collection("shoutouts").insertOne({
        shoutout_id: `so_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
        type: "players_club",
        scope: "global",
        agent_id: agent.agent_id,
        agent_name: agent.name,
        office: agent.office,
        ga_team_id: agent.ga_id,
        sales_day: sd,
        amount: agg.gross_alp,
        ts: nowUtc(),
      });
    }
  }

  const totalSales = await db
    .collection("production_entries")
    .aggregate([{ $match: { agent_id: agent.agent_id } }, { $group: { _id: null, sales: { $sum: "$sales" } } }])
    .toArray();
  if (totalSales.length && totalSales[0].sales === entry.sales && entry.sales > 0) {
    const existing = await db.collection("shoutouts").findOne({ type: "first_deal", agent_id: agent.agent_id });
    if (!existing) {
      await db.collection("shoutouts").insertOne({
        shoutout_id: `so_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
        type: "first_deal",
        scope: "ga_team",
        ga_team_id: agent.ga_id,
        agent_id: agent.agent_id,
        agent_name: agent.name,
        office: agent.office,
        sales_day: sd,
        ts: nowUtc(),
      });
    }
  }

  let streak = 0;
  const d = nowDetroit();
  for (let i = 0; i < 30; i += 1) {
    const sdi = salesDayFor(d.minus({ days: i }));
    const onTime = await db.collection("production_entries").findOne({
      agent_id: agent.agent_id,
      sales_day: sdi,
      submitted_on_time: true,
    });
    if (onTime) streak += 1;
    else break;
  }
  if (streak >= 5) {
    const existing = await db.collection("shoutouts").findOne({
      type: "streak",
      agent_id: agent.agent_id,
      streak,
    });
    if (!existing) {
      await db.collection("shoutouts").insertOne({
        shoutout_id: `so_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
        type: "streak",
        scope: "global",
        agent_id: agent.agent_id,
        agent_name: agent.name,
        office: agent.office,
        ga_team_id: agent.ga_id,
        sales_day: sd,
        streak,
        ts: nowUtc(),
      });
    }
  }
}

class SeededRandom {
  private seed = 42;

  next(): number {
    this.seed = (1664525 * this.seed + 1013904223) % 4294967296;
    return this.seed / 4294967296;
  }

  int(min: number, max: number): number {
    return Math.floor(this.next() * (max - min + 1)) + min;
  }

  choice<T>(items: readonly T[]): T {
    return items[this.int(0, items.length - 1)];
  }
}

async function seedData(req?: Request, payload?: AnyDoc | null) {
  const force = Boolean(payload?.force);
  const existing = await db.collection("agent_profiles").countDocuments({});

  if (force) {
    let user: AnyDoc;
    try {
      user = await getCurrentUser(req!);
    } catch {
      throw new HttpError(401, "Authenticated RGA required for force-reseed");
    }
    if (user.role !== "level_4") throw new HttpError(403, "Only RGA can force-reseed");
  }

  if (existing > 0 && !force) {
    return { ok: true, seeded: false, message: `Already seeded (${existing} agents)` };
  }

  if (force) {
    await Promise.all([
      db.collection("agent_profiles").deleteMany({}),
      db.collection("production_entries").deleteMany({}),
      db.collection("shoutouts").deleteMany({}),
      db.collection("audit_log").deleteMany({}),
      db.collection("historical_vault").deleteMany({}),
    ]);
  }

  const random = new SeededRandom();
  const firstNames = [
    "Marcus",
    "Tasha",
    "Jordan",
    "Avery",
    "Ricardo",
    "Sienna",
    "Devin",
    "Priya",
    "Hank",
    "Maya",
    "Theo",
    "Lena",
    "Jasper",
    "Cameron",
    "Brielle",
    "Omar",
    "Zara",
    "Nicolas",
    "Hailey",
    "Kingston",
    "Iris",
    "Tobias",
    "Gianna",
    "Bryson",
    "Laila",
    "Rashid",
    "Adriana",
    "Caleb",
    "Imani",
    "Diego",
    "Sloane",
    "Niko",
    "Selena",
    "Ezra",
    "Halle",
    "Cyrus",
    "Phoebe",
    "Malachi",
    "Esme",
    "Tristan",
    "Aria",
    "Lucian",
    "Maren",
    "Holden",
    "Saoirse",
    "Elias",
    "Wren",
    "Rohan",
    "Lyric",
    "Kade",
    "Magnolia",
    "Soren",
    "Briar",
    "Dax",
    "Vera",
    "Boaz",
    "Calla",
    "Reuben",
    "Indira",
    "Rocco",
    "Lyra",
    "Knox",
    "Mira",
    "Beck",
    "Astrid",
    "Ronan",
    "Hugo",
    "Nadia",
    "Adler",
    "Juno",
  ];
  const lastNames = [
    "Reyes",
    "Carter",
    "Nguyen",
    "Patel",
    "Brooks",
    "Rivera",
    "Bauer",
    "Sosa",
    "Donovan",
    "Wagner",
    "Pham",
    "Hayes",
    "Booker",
    "Ortiz",
    "Kim",
    "Bell",
    "Walsh",
    "Morgan",
    "Cole",
    "Hudson",
    "Mendez",
    "Lawson",
    "Greer",
    "Burke",
    "Salinas",
    "Vargas",
    "Holland",
    "Rios",
    "Faulkner",
    "Pearce",
    "Trent",
    "McKenzie",
    "Gallagher",
    "Briggs",
    "Frye",
    "Cassidy",
    "Locke",
    "Sutton",
    "Hartley",
    "Driscoll",
    "Pruitt",
    "Vance",
    "Whitford",
    "Crane",
    "Dunn",
    "Hollis",
    "Tate",
    "Quinn",
    "Rourke",
    "Slade",
  ];
  const states = ["MI", "OH", "IL", "IN", "WI", "KY", "MN", "MO", "TN", "NY", "TX", "FL", "CA", "GA", "NC", "PA", "VA", "MA"];
  const agents: AnyDoc[] = [];
  const usedEmails = new Set<string>();

  const namePool = () => `${random.choice(firstNames)} ${random.choice(lastNames)}`;
  const mkAgent = (
    role: Role,
    office: string,
    name: string,
    uplineId: string | null,
    gaId: string | null,
    isRookie = false,
  ) => {
    const [first, ...rest] = name.split(" ");
    const last = rest.join(" ") || "Smith";
    const baseEmail = `${first.toLowerCase()}.${last.toLowerCase()}`.replaceAll(" ", "");
    let email = `${baseEmail}@aopremiere.com`;
    let n = 1;
    while (usedEmails.has(email)) {
      n += 1;
      email = `${baseEmail}${n}@aopremiere.com`;
    }
    usedEmails.add(email);
    return {
      agent_id: `ag_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
      name,
      license: `LIC-${random.int(100000, 999999)}`,
      email,
      phone: `+1-${random.int(200, 999)}-${random.int(200, 999)}-${random.int(1000, 9999)}`,
      resident_state: random.choice(states),
      office,
      role,
      upline_id: uplineId,
      ga_id: gaId,
      is_rookie: isRookie,
      joined_at: DateTime.utc().minus({ days: random.int(15, 1000) }).toJSDate(),
    };
  };

  const rga = mkAgent("level_4", "Dearborn", "Vance Holloway", null, null);
  agents.push(rga);

  const mgas: AnyDoc[] = [];
  for (const office of ["MCM", "AMP", "Heritage", "Siren"]) {
    const mga = mkAgent("level_3", office, namePool(), rga.agent_id, null);
    mgas.push(mga);
    agents.push(mga);
  }

  const gas: AnyDoc[] = [];
  for (const mga of mgas) {
    for (let i = 0; i < 2; i += 1) {
      const ga = mkAgent("level_2", mga.office, namePool(), mga.agent_id, null);
      gas.push(ga);
      agents.push(ga);
    }
  }

  const agentsCount = 174 - agents.length;
  for (let i = 0; i < agentsCount; i += 1) {
    const ga = gas[i % gas.length];
    const office = random.next() < 0.7 ? ga.office : random.choice(OFFICES);
    agents.push(mkAgent("level_1", office, namePool(), ga.agent_id, ga.agent_id, random.next() < 0.3));
  }

  await db.collection("agent_profiles").insertMany(agents);

  const today = nowDetroit();
  const entries: AnyDoc[] = [];
  for (let dOffset = 0; dOffset < 7; dOffset += 1) {
    const dayLocal = today.minus({ days: dOffset });
    const salesDay = salesDayFor(dayLocal);
    for (const agent of agents) {
      if (agent.role !== "level_1" && agent.role !== "level_2" && random.next() >= 0.4) continue;
      if (random.next() < 0.2) continue;

      const sets = random.int(2, 10);
      const sits = random.int(1, Math.max(1, Math.min(8, sets)));
      const sales = random.int(0, Math.max(0, sits));
      const otsSits = random.int(0, sits);
      const otsSales = sales ? Math.min(sales, random.int(0, sales)) : 0;
      const refs = sales ? random.int(0, sales * 2) : 0;
      const refSits = random.int(0, refs);
      const avgAlp = random.choice([800, 1100, 1300, 1600, 2200, 3000, 4500]);
      const gross = Math.max(0, sales * avgAlp + (sales ? random.int(-200, 500) : 0));
      const minutesBack = dOffset === 0 ? random.int(0, random.next() < 0.7 ? 60 : 600) : random.int(60, 60 * 24);

      entries.push({
        entry_id: `pe_${randomUUID().replaceAll("-", "").slice(0, 12)}`,
        agent_id: agent.agent_id,
        office: agent.office,
        sales_day: salesDay,
        sets,
        sits,
        sales,
        ots_sits: otsSits,
        ots_sales: otsSales,
        n1: random.int(0, 2),
        refs_obtained: refs,
        ref_sits: refSits,
        ref_sales: random.int(0, refSits),
        pos_sits: random.int(0, Math.max(0, Math.floor(sits / 2))),
        pos_sales: random.int(0, Math.max(0, Math.floor(sits / 2))),
        vet_sits: random.int(0, Math.max(0, Math.floor(sits / 3))),
        vet_sales: random.int(0, Math.max(0, Math.floor(sits / 3))),
        gross_alp: gross,
        net_alp: gross,
        submitted_at: DateTime.utc().minus({ minutes: minutesBack }).toJSDate(),
        submitted_on_time: dOffset > 0 ? true : random.next() < 0.85,
      });
    }
  }
  if (entries.length) await db.collection("production_entries").insertMany(entries);

  for (const agent of agents) {
    const sdToday = currentSalesDayStr();
    const agg = await aggregateAlp({ agent_id: agent.agent_id, sales_day: sdToday });
    if (agg.gross_alp >= 10000) {
      await db.collection("shoutouts").insertOne({
        shoutout_id: `so_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
        type: "players_club",
        scope: "global",
        agent_id: agent.agent_id,
        agent_name: agent.name,
        office: agent.office,
        ga_team_id: agent.ga_id,
        sales_day: sdToday,
        amount: agg.gross_alp,
        ts: nowUtc(),
      });
    }
  }

  for (let week = 1; week < 9; week += 1) {
    const weekStart = today.minus({ days: week * 7 }).toISODate();
    const gross = random.int(180000, 450000);
    const net = Math.trunc(gross * (0.85 + random.next() * 0.15));
    const perOffice: AnyDoc = {};
    let rem = gross;
    for (const office of OFFICES.slice(0, -1)) {
      const slice = Math.trunc(rem * (0.1 + random.next() * 0.25));
      perOffice[office] = {
        gross_alp: slice,
        net_alp: Math.trunc(slice * 0.92),
        sales: random.int(10, 50),
        sits: random.int(20, 80),
      };
      rem -= slice;
    }
    perOffice[OFFICES[OFFICES.length - 1]] = {
      gross_alp: Math.max(0, rem),
      net_alp: Math.trunc(Math.max(0, rem) * 0.92),
      sales: random.int(10, 50),
      sits: random.int(20, 80),
    };

    await db.collection("historical_vault").insertOne({
      week_id: `wk_${randomUUID().replaceAll("-", "").slice(0, 8)}`,
      week_start: weekStart,
      archived_at: DateTime.utc().minus({ days: week * 7 }).toJSDate(),
      totals: {
        gross_alp: gross,
        net_alp: net,
        sales: random.int(80, 240),
        sits: random.int(150, 380),
      },
      by_office: perOffice,
      agent_count: 174,
    });
  }

  return { ok: true, seeded: true, agents: agents.length, entries: entries.length };
}

async function ensureIndexes() {
  await db.collection("user_sessions").createIndex("session_token", { unique: true });
  await db.collection("user_sessions").createIndex("expires_at");
  await db.collection("users").createIndex("email", { unique: true });
  await db.collection("agent_profiles").createIndex("agent_id", { unique: true });
  await db.collection("agent_profiles").createIndex("upline_id");
  await db.collection("agent_profiles").createIndex("office");
  await db.collection("production_entries").createIndex({ agent_id: 1, sales_day: 1 });
  await db.collection("production_entries").createIndex("submitted_at");
}

const app = express();
app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: "1mb" }));
app.use(cookieParser());

const api = express.Router();

api.get("/health", (_req, res) => res.json({ ok: true, service: "VantageLife 2.1 API" }));

api.post(
  "/auth/session",
  asyncHandler(async (req, res) => {
    const payload = sessionExchangeSchema.parse(req.body);
    const r = await fetch(EMERGENT_AUTH_URL, {
      headers: { "X-Session-ID": payload.session_id },
      signal: AbortSignal.timeout(15000),
    });
    if (!r.ok) throw new HttpError(401, "Invalid session_id");
    const data = (await r.json()) as AnyDoc;
    const email = data.email;
    const name = data.name || email;
    const sessionToken = data.session_token || `st_${randomUUID().replaceAll("-", "")}`;
    const user = await upsertUserAndSession({
      email,
      name,
      picture: data.picture,
      sessionToken,
      role: "level_1",
    });
    setSessionCookie(res, sessionToken);
    res.json(serializeDates({ user, session_token: sessionToken }));
  }),
);

api.post(
  "/auth/demo-login",
  asyncHandler(async (req, res) => {
    const payload = demoLoginSchema.parse(req.body);
    const emailMap: Record<Role, [string, string]> = {
      level_1: ["demo.agent@vantagelife.dev", "Demo Agent"],
      level_2: ["demo.ga@vantagelife.dev", "Demo GA"],
      level_3: ["demo.mga@vantagelife.dev", "Demo MGA"],
      level_4: ["demo.rga@vantagelife.dev", "Demo RGA"],
    };
    const [email, name] = emailMap[payload.level];
    const agent = await db.collection("agent_profiles").findOne({ role: payload.level }, { projection: { _id: 0 } });
    const agentId = agent?.agent_id || null;
    const sessionToken = `st_${randomUUID().replaceAll("-", "")}`;

    let user: AnyDoc | null = await db.collection("users").findOne({ email }, { projection: { _id: 0 } });
    if (user) {
      await db.collection("users").updateOne(
        { user_id: user.user_id },
        { $set: { role: payload.level, agent_id: agentId, name, picture: "" } },
      );
      user = await db.collection("users").findOne({ email }, { projection: { _id: 0 } });
    } else {
      user = {
        user_id: `user_${randomUUID().replaceAll("-", "").slice(0, 12)}`,
        email,
        name,
        picture: "",
        role: payload.level,
        agent_id: agentId,
        created_at: nowUtc(),
      };
      await db.collection("users").insertOne(user as AnyDoc);
    }

    await db.collection("user_sessions").insertOne({
      user_id: user!.user_id,
      session_token: sessionToken,
      created_at: nowUtc(),
      expires_at: DateTime.utc().plus({ days: 7 }).toJSDate(),
    });
    setSessionCookie(res, sessionToken);
    res.json(serializeDates({ user: omitId(user!), session_token: sessionToken, role_label: LEVELS[payload.level] }));
  }),
);

api.get(
  "/auth/me",
  requireAuth,
  asyncHandler(async (req, res) => {
    const user = req.user!;
    const agent = user.agent_id
      ? await db.collection("agent_profiles").findOne({ agent_id: user.agent_id }, { projection: { _id: 0 } })
      : null;
    res.json(serializeDates({ user, agent, role_label: LEVELS[(user.role || "level_1") as Role] || "Agent" }));
  }),
);

api.post(
  "/auth/logout",
  asyncHandler(async (req, res) => {
    const token = sessionTokenFrom(req);
    if (token) await db.collection("user_sessions").deleteOne({ session_token: token });
    res.clearCookie("session_token", { path: "/" });
    res.json({ ok: true });
  }),
);

api.get(
  "/dashboard/summary",
  requireAuth,
  asyncHandler(async (req, res) => {
    const ids = await visibleAgentIds(req.user!);
    const today = currentSalesDayStr();
    const yest = previousSalesDayStr();
    const base: AnyDoc = { sales_day: today };
    const baseY: AnyDoc = { sales_day: yest };
    if (ids !== null) {
      base.agent_id = { $in: ids };
      baseY.agent_id = { $in: ids };
    }
    const todayAgg = await aggregateAlp(base);
    const yestAgg = await aggregateAlp(baseY);
    const deltaPct = yestAgg.gross_alp > 0 ? ((todayAgg.gross_alp - yestAgg.gross_alp) / yestAgg.gross_alp) * 100 : 0;
    res.json({
      sales_day: today,
      total_alp: todayAgg.gross_alp,
      total_net_alp: todayAgg.net_alp,
      total_sits: todayAgg.sits,
      total_sales: todayAgg.sales,
      delta_pct_vs_yesterday: Math.round(deltaPct * 10) / 10,
      gate: gateState(),
      is_full_agency: ids === null,
    });
  }),
);

api.get(
  "/dashboard/ticker",
  requireAuth,
  asyncHandler(async (req, res) => {
    const ids = await visibleAgentIds(req.user!);
    const q: AnyDoc = { submitted_at: { $gte: DateTime.utc().minus({ minutes: 60 }).toJSDate() }, sales: { $gt: 0 } };
    if (ids !== null) q.agent_id = { $in: ids };
    const entries = await db
      .collection("production_entries")
      .find(q, { projection: { _id: 0 } })
      .sort({ submitted_at: -1 })
      .limit(50)
      .toArray();
    const items = [];
    for (const entry of entries) {
      const agent = await db.collection("agent_profiles").findOne({ agent_id: entry.agent_id }, { projection: { _id: 0 } });
      if (!agent) continue;
      items.push({
        agent_name: agent.name,
        alp: Number(entry.gross_alp || 0),
        market: agent.office || "",
        reps: Number(entry.refs_obtained || 0),
        ts: entry.submitted_at instanceof Date ? entry.submitted_at.toISOString() : entry.submitted_at,
      });
    }
    res.json({ items });
  }),
);

api.get(
  "/dashboard/platinum-wall",
  requireAuth,
  asyncHandler(async (req, res) => {
    const ids = await visibleAgentIds(req.user!);
    const q: AnyDoc = { sales_day: currentSalesDayStr() };
    if (ids !== null) q.agent_id = { $in: ids };
    const rows = await db
      .collection("production_entries")
      .aggregate([
        { $match: q },
        { $group: { _id: "$agent_id", gross_alp: { $sum: "$gross_alp" }, sales: { $sum: "$sales" } } },
        { $sort: { gross_alp: -1 } },
      ])
      .toArray();
    const vets: AnyDoc[] = [];
    const rookies: AnyDoc[] = [];
    for (const row of rows) {
      const agent = await db.collection("agent_profiles").findOne({ agent_id: row._id }, { projection: { _id: 0 } });
      if (!agent) continue;
      const item = {
        agent_id: agent.agent_id,
        name: agent.name,
        office: agent.office,
        gross_alp: Number(row.gross_alp || 0),
        sales: Number(row.sales || 0),
        is_rookie: Boolean(agent.is_rookie),
      };
      if (agent.is_rookie) {
        if (rookies.length < 3) rookies.push(item);
      } else if (vets.length < 3) vets.push(item);
      if (vets.length >= 3 && rookies.length >= 3) break;
    }
    res.json({ vets, rookies });
  }),
);

api.get(
  "/dashboard/offices",
  requireAuth,
  asyncHandler(async (req, res) => {
    const ids = await visibleAgentIds(req.user!);
    const today = currentSalesDayStr();
    const offices = [];
    for (const office of OFFICES) {
      const agentQ: AnyDoc = { office };
      if (ids !== null) agentQ.agent_id = { $in: ids };
      const officeAgentIds = (
        await db.collection("agent_profiles").find(agentQ, { projection: { _id: 0, agent_id: 1 } }).toArray()
      ).map((doc) => doc.agent_id);
      if (!officeAgentIds.length) {
        offices.push({ office, alp: 0, sales: 0, avg_deal: 0 });
        continue;
      }
      const agg = await aggregateAlp({ sales_day: today, agent_id: { $in: officeAgentIds } });
      offices.push({
        office,
        alp: Math.round(agg.gross_alp * 100) / 100,
        sales: agg.sales,
        avg_deal: agg.sales > 0 ? Math.round((agg.gross_alp / agg.sales) * 100) / 100 : 0,
      });
    }
    res.json({ offices });
  }),
);

api.post(
  "/pulse",
  requireAuth,
  asyncHandler(async (req, res) => {
    const payload = pulseSchema.parse(req.body);
    const user = req.user!;
    if (!user.agent_id) throw new HttpError(400, "No linked agent profile");
    const agent = await db.collection("agent_profiles").findOne({ agent_id: user.agent_id }, { projection: { _id: 0 } });
    if (!agent) throw new HttpError(404, "Agent not found");

    const nowLocal = nowDetroit();
    const entry = {
      entry_id: `pe_${randomUUID().replaceAll("-", "").slice(0, 12)}`,
      agent_id: user.agent_id,
      office: agent.office,
      sales_day: currentSalesDayStr(),
      sets: payload.sets,
      sits: payload.sits,
      sales: payload.sales,
      ots_sits: payload.ots_sits,
      ots_sales: payload.ots_sales,
      n1: payload.n1,
      refs_obtained: payload.refs_obtained,
      ref_sits: payload.ref_sits,
      ref_sales: payload.ref_sales,
      pos_sits: payload.pos_sits,
      pos_sales: payload.pos_sales,
      vet_sits: payload.vet_sits,
      vet_sales: payload.vet_sales,
      gross_alp: payload.gross_alp,
      net_alp: payload.gross_alp,
      submitted_at: nowUtc(),
      submitted_on_time: nowLocal.hour < 21,
    };
    await db.collection("production_entries").insertOne(entry);
    await maybeTriggerShoutouts(agent, entry);
    res.json(serializeDates({ ok: true, entry }));
  }),
);

api.get(
  "/pulse/me/today",
  requireAuth,
  asyncHandler(async (req, res) => {
    const user = req.user!;
    if (!user.agent_id) return res.json({ entries: [], totals: {}, gate: gateState() });
    const salesDay = currentSalesDayStr();
    const entries = await db
      .collection("production_entries")
      .find({ agent_id: user.agent_id, sales_day: salesDay }, { projection: { _id: 0 } })
      .sort({ submitted_at: -1 })
      .toArray();
    const totals = await aggregateAlp({ agent_id: user.agent_id, sales_day: salesDay });
    return res.json(serializeDates({ entries, totals, gate: gateState(), sales_day: salesDay }));
  }),
);

api.get(
  "/pulse/me/streak",
  requireAuth,
  asyncHandler(async (req, res) => {
    const user = req.user!;
    if (!user.agent_id) return res.json({ streak: 0 });
    let streak = 0;
    const d = nowDetroit();
    for (let i = 0; i < 30; i += 1) {
      const salesDay = salesDayFor(d.minus({ days: i }));
      const onTime = await db.collection("production_entries").findOne({
        agent_id: user.agent_id,
        sales_day: salesDay,
        submitted_on_time: true,
      });
      if (onTime) streak += 1;
      else break;
    }
    return res.json({ streak });
  }),
);

api.get(
  "/my-upline",
  requireAuth,
  asyncHandler(async (req, res) => {
    const user = req.user!;
    if (!user.agent_id) return res.json({ upline: null });
    const agent = await db.collection("agent_profiles").findOne(
      { agent_id: user.agent_id },
      { projection: { _id: 0, upline_id: 1 } },
    );
    if (!agent?.upline_id) return res.json({ upline: null });
    const upline = await db.collection("agent_profiles").findOne(
      { agent_id: agent.upline_id },
      { projection: { _id: 0, agent_id: 1, name: 1, role: 1, io_role: 1, phone: 1, email: 1, office: 1 } },
    );
    return res.json({ upline: upline ? omitId(upline) : null });
  }),
);

api.get(
  "/team",
  requireLevel(2),
  asyncHandler(async (req, res) => {
    const ids = await visibleAgentIds(req.user!);
    const today = currentSalesDayStr();
    const q: AnyDoc = { sales_day: today };
    if (ids !== null) q.agent_id = { $in: ids };
    const rows = await db
      .collection("production_entries")
      .aggregate([
        { $match: q },
        {
          $group: {
            _id: "$agent_id",
            gross_alp: { $sum: "$gross_alp" },
            net_alp: { $sum: "$net_alp" },
            sits: { $sum: "$sits" },
            sales: { $sum: "$sales" },
            refs_obtained: { $sum: "$refs_obtained" },
          },
        },
        { $sort: { gross_alp: -1 } },
      ])
      .toArray();
    const agentQ: AnyDoc = {};
    if (ids !== null) agentQ.agent_id = { $in: ids };
    const agents = new Map(
      (await db.collection("agent_profiles").find(agentQ, { projection: { _id: 0 } }).toArray()).map((agent) => [
        agent.agent_id,
        agent,
      ]),
    );
    const team = [];
    for (const row of rows) {
      const agent = agents.get(row._id);
      if (!agent) continue;
      const sales = Number(row.sales || 0);
      const sits = Number(row.sits || 0);
      const close = sits > 0 ? (sales / sits) * 100 : 0;
      const avgDeal = sales > 0 ? Number(row.gross_alp || 0) / sales : 0;
      const alerts = [];
      if (sits >= 3 && close < 50) alerts.push("low_close_ratio");
      if (sales >= 1 && avgDeal < 1200) alerts.push("low_avg_deal");
      team.push({
        agent_id: agent.agent_id,
        name: agent.name,
        office: agent.office,
        role: agent.role,
        io_role: agent.io_role || "",
        phone: agent.phone || "",
        email: agent.email || "",
        is_rookie: Boolean(agent.is_rookie),
        gross_alp: Number(row.gross_alp || 0),
        net_alp: Number(row.net_alp || 0),
        sits,
        sales,
        close_ratio: Math.round(close * 10) / 10,
        avg_deal: Math.round(avgDeal * 100) / 100,
        alerts,
      });
    }
    const listed = new Set(team.map((item) => item.agent_id));
    for (const [agentId, agent] of agents) {
      if (listed.has(agentId)) continue;
      team.push({
        agent_id: agentId,
        name: agent.name,
        office: agent.office,
        role: agent.role,
        io_role: agent.io_role || "",
        phone: agent.phone || "",
        email: agent.email || "",
        is_rookie: Boolean(agent.is_rookie),
        gross_alp: 0,
        net_alp: 0,
        sits: 0,
        sales: 0,
        close_ratio: 0,
        avg_deal: 0,
        alerts: ["no_pulse"],
      });
    }
    res.json({ team, sales_day: today });
  }),
);

api.get(
  "/shoutouts",
  requireAuth,
  asyncHandler(async (req, res) => {
    const user = req.user!;
    const userAgent = user.agent_id
      ? await db.collection("agent_profiles").findOne({ agent_id: user.agent_id }, { projection: { _id: 0 } })
      : null;
    const shoutouts = await db.collection("shoutouts").find({}, { projection: { _id: 0 } }).sort({ ts: -1 }).limit(200).toArray();
    const out = shoutouts.filter((shoutout) => {
      const scope = shoutout.scope || "global";
      if (scope === "global") return true;
      if (scope === "ga_team") {
        if (user.role === "level_4") return true;
        if (userAgent && (userAgent.ga_id === shoutout.ga_team_id || user.agent_id === shoutout.ga_team_id)) return true;
        if (user.agent_id === shoutout.agent_id) return true;
      }
      return false;
    });
    res.json(serializeDates({ shoutouts: out }));
  }),
);

api.post(
  "/manager/erase",
  requireLevel(4),
  asyncHandler(async (req, res) => {
    const payload = eraseSchema.parse(req.body);
    if (payload.reason.trim().length < 10) throw new HttpError(400, "Reason must be at least 10 characters");
    const agent = await db.collection("agent_profiles").findOne({ agent_id: payload.agent_id }, { projection: { _id: 0 } });
    if (!agent) throw new HttpError(404, "Agent not found");

    const agg = await aggregateAlp({ agent_id: payload.agent_id, sales_day: payload.sales_day });
    const originalNet = agg.net_alp;
    const delta = payload.new_alp - originalNet;
    const adj = {
      entry_id: `adj_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
      agent_id: payload.agent_id,
      office: agent.office,
      sales_day: payload.sales_day,
      sets: 0,
      sits: 0,
      sales: 0,
      ots_sits: 0,
      ots_sales: 0,
      n1: 0,
      refs_obtained: 0,
      ref_sits: 0,
      ref_sales: 0,
      pos_sits: 0,
      pos_sales: 0,
      vet_sits: 0,
      vet_sales: 0,
      gross_alp: 0,
      net_alp: delta,
      submitted_at: nowUtc(),
      submitted_on_time: true,
      is_adjustment: true,
      reason: payload.reason,
    };
    await db.collection("production_entries").insertOne(adj);
    const audit = {
      audit_id: `au_${randomUUID().replaceAll("-", "").slice(0, 10)}`,
      ts: nowUtc(),
      action: "adjust_alp",
      agent_id: payload.agent_id,
      agent_name: agent.name,
      changed_by: req.user!.user_id,
      changed_by_name: req.user!.name,
      original_value: originalNet,
      new_value: payload.new_alp,
      delta,
      sales_day: payload.sales_day,
      reason: payload.reason,
    };
    await db.collection("audit_log").insertOne(audit);
    res.json(serializeDates({ ok: true, audit, delta }));
  }),
);

api.get(
  "/manager/audit",
  requireLevel(4),
  asyncHandler(async (_req, res) => {
    const items = await db.collection("audit_log").find({}, { projection: { _id: 0 } }).sort({ ts: -1 }).limit(200).toArray();
    res.json(serializeDates({ items }));
  }),
);

api.get(
  "/vault/weeks",
  requireLevel(4),
  asyncHandler(async (_req, res) => {
    const weeks = await db
      .collection("historical_vault")
      .find({}, { projection: { _id: 0 } })
      .sort({ week_start: -1 })
      .limit(8)
      .toArray();
    res.json(serializeDates({ weeks }));
  }),
);

api.get(
  "/vault/compare",
  requireLevel(4),
  asyncHandler(async (req, res) => {
    const weekA = String(req.query.week_a || "");
    const weekB = String(req.query.week_b || "");
    const a = await db.collection("historical_vault").findOne({ week_start: weekA }, { projection: { _id: 0 } });
    const b = await db.collection("historical_vault").findOne({ week_start: weekB }, { projection: { _id: 0 } });
    if (!a || !b) throw new HttpError(404, "Week not found");
    const delta: AnyDoc = {};
    for (const metric of ["gross_alp", "net_alp", "sales", "sits"]) {
      const av = Number(a.totals?.[metric] || 0);
      const bv = Number(b.totals?.[metric] || 0);
      delta[metric] = { a: av, b: bv, delta: bv - av, pct: av ? Math.round(((bv - av) / av) * 1000) / 10 : 0 };
    }
    res.json(serializeDates({ a, b, delta }));
  }),
);

api.post(
  "/admin/wednesday-reset",
  requireLevel(4),
  asyncHandler(async (_req, res) => {
    const today = nowDetroit();
    const daysSinceWed = (today.weekday - 3 + 7) % 7;
    const weekStart = today.minus({ days: daysSinceWed }).toISODate();
    const docs = await db
      .collection("production_entries")
      .aggregate([
        {
          $group: {
            _id: null,
            gross_alp: { $sum: "$gross_alp" },
            net_alp: { $sum: "$net_alp" },
            sits: { $sum: "$sits" },
            sales: { $sum: "$sales" },
          },
        },
      ])
      .toArray();
    const d = docs[0] || {};
    const totals = {
      gross_alp: Number(d.gross_alp || 0),
      net_alp: Number(d.net_alp || 0),
      sits: Number(d.sits || 0),
      sales: Number(d.sales || 0),
    };
    const byOffice: AnyDoc = {};
    for (const office of OFFICES) {
      const agentIds = (
        await db.collection("agent_profiles").find({ office }, { projection: { _id: 0, agent_id: 1 } }).toArray()
      ).map((agent) => agent.agent_id);
      byOffice[office] = await aggregateAlp({ agent_id: { $in: agentIds } });
    }
    const snapshot = {
      week_id: `wk_${randomUUID().replaceAll("-", "").slice(0, 8)}`,
      week_start: weekStart,
      archived_at: nowUtc(),
      totals,
      by_office: byOffice,
      agent_count: await db.collection("agent_profiles").countDocuments({}),
    };
    await db.collection("historical_vault").insertOne(snapshot);
    await db.collection("production_entries").deleteMany({});
    res.json(serializeDates({ ok: true, snapshot }));
  }),
);

api.post(
  "/seed",
  asyncHandler(async (req, res) => {
    res.json(await seedData(req, req.body));
  }),
);

app.use("/api", api);

app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (err instanceof z.ZodError) {
    return res.status(400).json({ detail: err.errors[0]?.message || "Invalid request" });
  }
  if (err instanceof HttpError) {
    return res.status(err.status).json({ detail: err.detail });
  }
  console.error(err);
  return res.status(500).json({ detail: "Internal server error" });
});

async function start() {
  await client.connect();
  db = client.db(DB_NAME);
  await ensureIndexes();

  const count = await db.collection("agent_profiles").countDocuments({});
  if (count === 0) {
    try {
      await seedData();
      console.info("Auto-seeded mock data on first run.");
    } catch (error) {
      console.error("Auto-seed failed:", error);
    }
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.info(`VantageLife API listening on ${PORT}`);
  });
}

process.on("SIGINT", async () => {
  await client.close();
  process.exit(0);
});

process.on("SIGTERM", async () => {
  await client.close();
  process.exit(0);
});

start().catch((error) => {
  console.error(error);
  process.exit(1);
});
