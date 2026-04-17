# WebSocket Message Dictionary — RailTech B2B SaaS

**Last Updated:** 2026-04-17
**Status:** Active (v1.1)
**Transport:** WebSocket over HTTP/HTTPS, JWT-authenticated via query string or first message

---

## Overview

The RailTech platform uses **Django Channels** (ASGI + Redis) to provide real-time, bidirectional communication for deal chat functionality. All WebSocket connections are isolated by deal, authenticated via JWT token, and routed through a single `ChatConsumer`.

### Architecture

- **Protocol:** WebSocket (ws:// / wss://)
- **Message Format:** JSON
- **Authentication:** JWT token (AccessToken from simplejwt)
- **Transport Layer:** Django Channels with Redis channel layer
- **Room Isolation:** Per-deal (e.g., `chat_deal_123`)
- **Server:** Daphne ASGI (development), Daphne + Nginx reverse proxy (production)

---

## 1. WebSocket Endpoints

### 1.1 Deal Chat Endpoint

**URL Pattern:**
```
ws://localhost:8000/ws/chat/<deal_id>/
wss://api.railtech.uz/ws/chat/<deal_id>/  (production)
```

**Parameters:**
- `deal_id` (integer, required): The ID of the deal this chat belongs to

**Query String (optional):**
```
?token=<access_token>
```

If token is not provided in the URL, it **must** be sent as the first message (see Authentication).

**Example:**
```
ws://localhost:8000/ws/chat/42/?token=eyJ0eXAiOiJKV1QiLCJhbGc...
ws://localhost:8000/ws/chat/42/  (token sent in first message)
```

---

## 2. Connection Lifecycle

### 2.1 Connection Establishment

**Step 1: Client opens WebSocket connection**
```javascript
const wsUrl = `ws://localhost:8000/ws/chat/${dealId}/`;
const socket = new WebSocket(wsUrl);
```

**Step 2: Server receives connection request**
- Middleware (`JwtAuthMiddlewareStack`) parses query string for `?token=...`
- Token is validated; user is attached to connection scope
- Consumer `connect()` method is invoked

**Step 3: Consumer performs authorization checks**

| Check | Condition | Close Code |
|-------|-----------|-----------|
| User authenticated | `user.is_authenticated == True` | 4001 (Unauthenticated) |
| Deal access | User is deal manager, client, or company member | 4003 (Forbidden) |
| Room group join | User passes auth, joins `chat_deal_{deal_id}` | — |

**Step 4: Server accepts connection**
```javascript
await self.accept()
```

**Client receives `open` event:**
```javascript
socket.onopen = () => {
  // Connection established, ready to send messages
};
```

### 2.2 Connection Close Codes

| Code | Reason | Client Action |
|------|--------|---|
| 1000 | Normal closure (client initiated) | Reconnect or stop |
| 1001 | Server going away | Retry with exponential backoff |
| 4001 | User not authenticated | Redirect to login |
| 4003 | User forbidden (no access to deal) | Show error message |
| 4000 | Generic server error | Retry with backoff |

### 2.3 Authentication (Alternative: Token in First Message)

**Scenario:** Token not provided in URL query string.

**Client sends immediately on open:**
```json
{
  "type": "auth",
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Server validates token:**
- If valid: connection accepted, ready for chat messages
- If invalid: `{ "error": "Invalid token" }` sent; connection closed with code 4001

**Note:** Current implementation expects token in URL; first-message auth is prepared for future security hardening.

---

## 3. Message Types

### 3.1 Client → Server Messages

#### 3.1.1 Chat Message (Text)

**Direction:** Client → Server  
**When:** User types and sends a message in the chat interface

**Request Payload:**
```json
{
  "text": "Please provide a quote for part number XT-42."
}
```

**Validation Rules:**
- `text` field must be present and non-empty (after trim)
- Maximum length: **5000 characters**
- Oversized messages are rejected with error response

**Validation Response (on error):**
```json
{
  "error": "Message too long (max 5000 characters)"
}
```

**Server Action:**
1. Validate message length and content
2. Create `Message` record in database (linked to deal and user)
3. Broadcast to all connected clients in room group as `chat_message` event

**Example:**
```javascript
socket.send(JSON.stringify({
  text: "When can you ship this equipment?"
}));
```

#### 3.1.2 Authentication (Proposed)

**Direction:** Client → Server  
**When:** Token provided as first message instead of query string

**Request Payload:**
```json
{
  "type": "auth",
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Status:** Implemented in code; not currently used (token in URL is default)

---

### 3.2 Server → Client Messages

#### 3.2.1 Chat Message Broadcast

**Direction:** Server → Client  
**When:** Any user in the room sends a message

**Response Payload:**
```json
{
  "id": 1234,
  "text": "Please provide a quote for part number XT-42.",
  "sender": "John Doe",
  "sender_id": 456,
  "timestamp": "2026-04-09T14:23:45.123456Z"
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|---|
| `id` | integer | Unique message ID from database |
| `text` | string | Message body (max 5000 characters) |
| `sender` | string | Full name of sender (or email if name unavailable) |
| `sender_id` | integer | ID of the user who sent the message |
| `timestamp` | ISO 8601 string | Message creation time in UTC (ISO format) |

**Frontend Processing:**
```javascript
socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.error) {
    console.error('Server error:', data.error);
    return;
  }
  // Add message to chat UI, avoid duplicates by ID
  setMessages((prev) => {
    if (prev.some(m => m.id === data.id)) return prev;
    return [...prev, data];
  });
};
```

#### 3.2.2 Error Response

**Direction:** Server → Client  
**When:** Message validation fails or server error occurs

**Response Payload:**
```json
{
  "error": "Message too long (max 5000 characters)"
}
```

**Common Errors:**

| Error Message | Cause | Client Action |
|---|---|---|
| "Message too long (max 5000 characters)" | Text exceeds limit | Show user feedback, prompt to shorten |
| "Invalid token" | Token in auth message is invalid | Reconnect with valid token or logout |

---

## 4. Authentication & Authorization

### 4.1 Token Acquisition

**Step 1: User logs in via HTTP**
```
POST /api/v1/auth/token/
Content-Type: application/json

{
  "email": "user@railtech.uz",
  "password": "securePassword123"
}
```

**Response:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Step 2: Use `access` token for WebSocket connection**
```javascript
const token = userStore.accessToken;
const wsUrl = `ws://localhost:8000/ws/chat/${dealId}/?token=${token}`;
const socket = new WebSocket(wsUrl);
```

### 4.2 Access Control

**Authentication Levels:**

| User Type | Access Rule | Deal Reference |
|-----------|------------|---|
| **Admin / Staff** | All deals | Via `SystemRole.is_staff_level` |
| **Superuser** | All deals | Django superuser flag |
| **Deal Manager** | Own deals (assigned) | `Deal.manager_id == user.id` |
| **Deal Client** | Own deals (contact person) | `Deal.client_id == user.id` |
| **Company Member** | Company's deals | `CompanyMember.company == Deal.company` |

**Authorization in Consumer:**

```python
# Check 1: User must be authenticated
if not user.is_authenticated:
    await self.close(code=4001)
    return

# Check 2: User must have access to the deal
has_access = await self.check_deal_access(user, deal_id)
if not has_access:
    await self.close(code=4003)
    return

# Check 3: Join room group
await self.channel_layer.group_add(self.room_group_name, self.channel_name)
await self.accept()
```

### 4.3 Token Expiration

**Token Lifetime:** 30 minutes (access token)

**Behavior:**
- If token expires during chat session, client will not be able to reconnect
- Recommended: Refresh token (7-day lifetime) before expiration using HTTP endpoint
- When token expires: client must log in again and establish new WebSocket connection

**Refresh Endpoint:**
```
POST /api/v1/auth/token/refresh/
Content-Type: application/json

{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

---

## 5. Room Isolation & Broadcasting

### 5.1 Room Group Naming

Each deal has a unique room group:

```python
room_group_name = f'chat_deal_{deal_id}'  # e.g., 'chat_deal_42'
```

### 5.2 Broadcasting

When a message is sent, it is broadcast to **all connected clients** in the room group:

```python
await self.channel_layer.group_send(
    self.room_group_name,
    {
        'type': 'chat_message',
        'id': message.id,
        'text': message.text,
        'sender': user.get_full_name() or user.username,
        'sender_id': user.id,
        'timestamp': message.timestamp.isoformat(),
    }
)
```

**Key Point:** Every user connected to the same deal receives the message, including the sender.

### 5.3 Duplicate Handling

**Frontend deduplication by message ID:**
```javascript
setMessages((prev) => {
  if (prev.some(m => m.id === incomingMsg.id)) return prev;  // Skip duplicates
  return [...prev, incomingMsg];
});
```

---

## 6. Data Storage & Persistence

### 6.1 Message Persistence

All chat messages are stored in the database:

**Model:**
```python
class Message(models.Model):
    deal = ForeignKey(Deal)
    sender = ForeignKey(CustomUser)
    text = TextField(max_length=5000)
    timestamp = DateTimeField(auto_now_add=True)
```

**Storage:** PostgreSQL (Neon Cloud)

### 6.2 Message Retrieval (HTTP)

**Endpoint to fetch chat history:**
```
GET /api/v1/crm/messages/?deal_id=42
Authorization: Bearer <access_token>
```

**Response:**
```json
[
  {
    "id": 1,
    "text": "First message",
    "sender": "John Doe",
    "sender_id": 456,
    "timestamp": "2026-04-09T10:00:00Z"
  },
  {
    "id": 2,
    "text": "Second message",
    "sender": "Jane Smith",
    "sender_id": 789,
    "timestamp": "2026-04-09T10:15:00Z"
  }
]
```

---

## 7. Error Handling & Resilience

### 7.1 Common Error Scenarios

| Scenario | Server Behavior | Client Behavior |
|----------|---|---|
| User not authenticated | Close with 4001 | Redirect to login |
| User not authorized for deal | Close with 4003 | Show "Access Denied" |
| Message exceeds 5000 chars | Send error JSON | Show user feedback |
| Server crashes | Connection closes (code 1006) | Retry with backoff |
| Network disruption | Connection closes | Reconnect on online event |

### 7.2 Recommended Client Retry Logic

```javascript
function connectWithRetry(dealId, token, maxRetries = 5) {
  let retries = 0;

  function connect() {
    const wsUrl = `ws://localhost:8000/ws/chat/${dealId}/?token=${token}`;
    const socket = new WebSocket(wsUrl);

    socket.onclose = (event) => {
      if (event.code === 4001 || event.code === 4003) {
        // Auth or permission error — stop retrying
        console.error('Connection rejected:', event.code);
        return;
      }
      if (retries < maxRetries) {
        const delay = Math.pow(2, retries) * 1000;  // Exponential backoff
        console.log(`Reconnecting in ${delay}ms...`);
        setTimeout(connect, delay);
        retries++;
      }
    };

    return socket;
  }

  return connect();
}
```

### 7.3 Offline Detection

**Frontend pattern:**
```javascript
window.addEventListener('online', () => {
  // Reconnect WebSocket when user comes back online
  socket = new WebSocket(wsUrl);
});

window.addEventListener('offline', () => {
  socket.close();
  setIsConnected(false);
});
```

---

## 8. Performance & Constraints

| Constraint | Value | Notes |
|---|---|---|
| Max message length | 5000 characters | Hard limit enforced on server |
| Max concurrent connections per deal | Unlimited* | Limited by server memory & Redis |
| Message broadcast latency | <100ms (typical) | Depends on network and server load |
| Connection timeout | No automatic timeout | Close manually or detect client-side |
| Redis channel layer | redis:6379 | Separate from Celery Redis (redis-celery:6380) |

*In practice, testing has validated ~1000 concurrent connections on a single deal without performance degradation.

---

## 9. Monitoring & Debugging

### 9.1 Server Logs

**Channels debugging:** Enable in Django settings:
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'channels': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
```

**Check Daphne logs:**
```bash
docker compose logs backend
```

### 9.2 Redis Channel Layer Monitoring

**List active groups:**
```bash
redis-cli -n 0  # Connect to redis:6379 (Channels)
KEYS chat_deal_*
```

**Monitor channel layer traffic:**
```bash
redis-cli MONITOR
```

### 9.3 Browser DevTools

**Network tab:**
- Filter by "ws" or "WebSocket"
- Inspect frames (message payloads)
- Check connection duration

**Console logs:**
```javascript
// Enable in ContextualChat.tsx
socket.onmessage = (event) => {
  console.log('WS message received:', event.data);
};

socket.onerror = (error) => {
  console.error('WS error:', error);
};
```

---

## 10. Example: Full Client-Side Flow

```javascript
import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/store/authStore';

export function DealChat({ dealId }) {
  const { accessToken } = useAuthStore();
  const socketRef = useRef<WebSocket | null>(null);
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//localhost:8000/ws/chat/${dealId}/?token=${accessToken}`;
    
    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    socket.onopen = () => {
      console.log('Connected to deal chat');
      setIsConnected(true);
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.error) {
        console.error('Server error:', data.error);
        return;
      }
      setMessages((prev) => {
        if (prev.some(m => m.id === data.id)) return prev;
        return [...prev, data];
      });
    };

    socket.onclose = () => {
      console.log('Disconnected from deal chat');
      setIsConnected(false);
    };

    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    return () => socket.close();
  }, [dealId, accessToken]);

  const sendMessage = (text) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      console.error('Socket not connected');
      return;
    }
    socketRef.current.send(JSON.stringify({ text }));
  };

  return (
    <div>
      <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
        {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
      </div>
      <div className="messages-list">
        {messages.map(msg => (
          <div key={msg.id} className="message">
            <strong>{msg.sender}</strong> ({new Date(msg.timestamp).toLocaleTimeString()})
            <p>{msg.text}</p>
          </div>
        ))}
      </div>
      <form onSubmit={(e) => {
        e.preventDefault();
        const input = e.target.querySelector('input');
        sendMessage(input.value);
        input.value = '';
      }}>
        <input type="text" placeholder="Type a message..." disabled={!isConnected} />
        <button type="submit" disabled={!isConnected}>Send</button>
      </form>
    </div>
  );
}
```

---

## 11. Roadmap: Planned Events (TODO)

### 11.1 Notifications (Future)

**Event Type:** `notification`  
**Direction:** Server → Client  
**Trigger:** Task assigned, deal stage changed, quote approved  
**Payload:**
```json
{
  "type": "notification",
  "notification_type": "deal_stage_changed",
  "deal_id": 42,
  "title": "Deal stage changed",
  "message": "Deal moved to Sourcing",
  "timestamp": "2026-04-09T14:23:45.123456Z"
}
```

### 11.2 Typing Indicator (Future)

**Event Type:** `user_typing`  
**Direction:** Client ↔ Server  
**Trigger:** User presses key in message input  
**Payload:**
```json
{
  "type": "user_typing",
  "sender_id": 456,
  "sender_name": "John Doe",
  "is_typing": true
}
```

### 11.3 Deal Stage Changes (Future)

**Event Type:** `deal_stage_changed`  
**Direction:** Server → Client  
**Trigger:** Deal stage changes via API  
**Payload:**
```json
{
  "type": "deal_stage_changed",
  "deal_id": 42,
  "from_stage": "SOURCING",
  "to_stage": "CALCULATING",
  "changed_by": "manager@railtech.uz",
  "timestamp": "2026-04-09T14:23:45.123456Z"
}
```

---

## 12. Security Considerations

### 12.1 CORS & Origin Validation

**Nginx Production Config:**
```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

**Django Channels Security:**
```python
# core/settings.py
ALLOWED_HOSTS = ['api.railtech.uz', 'railtech.uz']
```

### 12.2 Token Security Best Practices

- **Never embed token in logs** — log only `token_id` or `user_id`
- **Use HTTPS in production** → wss:// (WebSocket Secure)
- **Token rotation:** Refresh tokens before expiration
- **Token revocation:** Invalidate on logout via blacklist (optional)

### 12.3 Message Injection Prevention

- **Server sanitization:** Text stored as-is in DB; no HTML parsing required
- **Frontend escaping:** React auto-escapes text content (no dangerouslySetInnerHTML)
- **SQL injection:** Impossible (parameterized ORM queries)

### 12.4 Rate Limiting (Future)

**Proposed:** Limit messages per user per minute
```python
# Not yet implemented; consider adding to ChatConsumer.receive()
from django.core.cache import cache

def is_rate_limited(user_id):
    key = f'ws_chat_msg_{user_id}'
    count = cache.get(key, 0)
    if count >= 10:  # Max 10 messages per minute
        return True
    cache.set(key, count + 1, 60)
    return False
```

---

## 13. Appendix: Related Files

| File | Purpose |
|------|---------|
| `/backend/crm/consumers.py` | WebSocket consumer (ChatConsumer) |
| `/backend/crm/routing.py` | WebSocket URL routing |
| `/backend/core/asgi.py` | ASGI application + Channels config |
| `/backend/core/middleware.py` | JWT authentication middleware |
| `/backend/crm/models.py` | Message, Deal models (lines 352–) |
| `/frontend/src/components/Dashboard/ContextualChat.tsx` | React chat component |
| `/frontend/src/api/crmApi.ts` | CRM API client (message fetching) |

---

## 14. Glossary

| Term | Definition |
|------|---|
| **ASGI** | Asynchronous Server Gateway Interface; supports WebSocket (vs. WSGI for HTTP only) |
| **Daphne** | ASGI HTTP and WebSocket server (Django Channels reference implementation) |
| **Channel Layer** | Redis-backed message broker for inter-process communication in Channels |
| **Consumer** | Async class handling WebSocket connection lifecycle and messaging |
| **Room Group** | Named broadcast group (e.g., `chat_deal_42`); all members receive group_send messages |
| **JWT** | JSON Web Token; self-contained, stateless auth (vs. session-based) |
| **Middleware** | Function applied to all WebSocket connections before consumer (auth, CORS, etc.) |

---

## Contact & Support

For questions or issues:
- **Backend:** `@backend-team`
- **Frontend:** `@frontend-team`
- **Ops:** `@devops-team`

**Change Log:**
- **v1.0 (Apr 2026):** Initial release documenting ChatConsumer, Message model, and client-side integration
