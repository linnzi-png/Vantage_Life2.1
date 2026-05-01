# Auth-Gated App Testing Playbook

## Step 1: Create Test User & Session
```bash
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  role: 'level_4',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Test Backend API
```bash
curl -X GET "$EXPO_PUBLIC_BACKEND_URL/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## Step 3: Demo Login (No Google Required)
The app exposes `/api/auth/demo-login` with body `{"level": "level_1" | "level_2" | "level_3" | "level_4"}` for fast RBAC testing.
This returns `{ session_token, user }` and also sets the session_token cookie.

## RBAC Roles
- level_1 = Agent (personal stats + pulse entry)
- level_2 = GA / Co-Executive Producer (team view)
- level_3 = MGA / Executive Producer (full agency)
- level_4 = RGA / Executive (global + eraser + vault)

## Checklist
- [ ] User has `user_id` field (UUID)
- [ ] Session `user_id` matches user
- [ ] All Mongo queries use `{"_id": 0}` projection
- [ ] `/api/auth/me` returns user without 401
