# Auth-Gated App Testing Playbook

## The two-step model (test both halves)

1. **Authentication** — any verified Google or Apple identity signs in successfully.
2. **Authorization** — a separate `agent_profiles` lookup by email. Roster match →
   real role (`level_1..level_4`) + `agent_id`; no match → role `"pending"`, no
   `agent_id`, and the read-only "Account Pending" screen. Business-data routes
   reject pending users via `require_agent` (403), never with an auth error.

## Step 1: Demo Login (preferred — no Google/Apple needed)

`POST /api/auth/demo-login` with body `{"level": "level_1" | "level_2" | "level_3" | "level_4"}`.
Returns `{ session_token, user }` and sets the `session_token` cookie. Fastest way
to exercise each RBAC tier.

```bash
curl -X POST "$EXPO_PUBLIC_BACKEND_URL/api/auth/demo-login" \
  -H "Content-Type: application/json" \
  -d '{"level": "level_4"}'
```

## Step 2: Verify the session

```bash
curl -X GET "$EXPO_PUBLIC_BACKEND_URL/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## Step 3: Manual user/session (when you need a specific email or a pending user)

```bash
mongosh --eval "
use('YOUR_DB_NAME');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: '',
  role: 'level_4',        // use 'pending' with agent_id: null to test the authorization gate
  agent_id: 'AGENT_ID_FROM_agent_profiles',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
"
```

## RBAC Roles

- `level_1` = Agent (personal stats + pulse entry)
- `level_2` = GA (team view)
- `level_3` = MGA (full agency)
- `level_4` = RGA (global + eraser + vault + weekly reset)
- `pending` = authenticated but not on the agent roster (read-only pending screen)

## Checklist

- [ ] User has `user_id` field (UUID)
- [ ] Session `user_id` matches user
- [ ] All Mongo queries use `{"_id": 0}` projection
- [ ] `/api/auth/me` returns user without 401
- [ ] A `pending` user gets 403 from business-data routes, not 401
- [ ] Each tier only sees agents returned by `visible_agent_ids()` for their level
