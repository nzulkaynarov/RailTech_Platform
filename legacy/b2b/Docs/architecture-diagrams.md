# RailTech B2B SaaS — Architecture Diagrams

**Last Updated:** 2026-04-17

Mermaid-диаграммы ключевых потоков и архитектуры RailTech. Источник правды по моделям — [technical-specification.md](technical-specification.md); по стадиям сделки — [business-logic.md](business-logic.md).

> **Примечание:** На схеме мульти-тенантности блок `RFQRequest` — концептуальный (часть Sprint 4). В текущей реализации RFQ моделируется через `Deal` + `QuoteItem` (см. [business-logic.md](business-logic.md) §2.3).

---

## 1. Deal FSM (State Diagram)

The deal lifecycle follows a finite state machine with clear transitions:

```mermaid
stateDiagram-v2
    [*] --> DRAFT: New Deal Created

    DRAFT --> KYC_PENDING: Client Submits Profile
    
    KYC_PENDING --> SOURCING: Admin Approves KYC (L2 Verification)
    KYC_PENDING --> DRAFT: Client Revises Profile
    
    SOURCING --> CALCULATING: All Items Sourced\n(RFQ Responses Received)
    
    CALCULATING --> QUOTE_SENT: Quote Generated & Sent\n(WeasyPrint PDF)
    
    QUOTE_SENT --> CONTRACT_SIGNED: Client Approves Quote
    QUOTE_SENT --> CLOSED_LOST: Client Rejects Quote
    
    CONTRACT_SIGNED --> CLOSED_WON: Order Fulfilled\n(Delivery Completed)
    
    DRAFT --> CLOSED_LOST: Seller Cancels
    KYC_PENDING --> CLOSED_LOST: Deal Cancelled
    SOURCING --> CLOSED_LOST: Deal Cancelled
    CALCULATING --> CLOSED_LOST: Deal Cancelled
    QUOTE_SENT --> CLOSED_LOST: Deal Cancelled (Before Approval)
    
    CLOSED_WON --> [*]
    CLOSED_LOST --> [*]
```

**Stage Details:**
- **DRAFT**: Deal created, waiting for company profile completion
- **KYC_PENDING**: Company profile submitted, awaiting admin L2 verification
- **SOURCING**: KYC approved, sourcing RFQs sent to manufacturers
- **CALCULATING**: Items quoted by manufacturers, quote being calculated
- **QUOTE_SENT**: Final quote generated and sent to client for approval
- **CONTRACT_SIGNED**: Client approved quote, deal moving to fulfillment
- **CLOSED_WON**: Order delivered, deal won
- **CLOSED_LOST**: Deal cancelled or client rejected quote

---

## 2. KYC Verification Flow (Sequence Diagram)

The Know-Your-Customer (KYC) process includes document verification and two-level status tracking:

```mermaid
sequenceDiagram
    participant Client as Client<br/>(Web)
    participant Backend as Django Backend
    participant Email as Email Service
    participant Admin as Admin Dashboard
    participant Manager as KYC Manager

    Client->>Backend: POST /api/v1/auth/register/
    activate Backend
    Backend->>Backend: Create CustomUser(is_active=False)
    Backend->>Email: Send verification email with link
    Backend-->>Client: 201 User created (check email)
    deactivate Backend

    Email->>Client: Email with /setup-password?uid=X&token=Y

    Client->>Backend: GET /setup-password?uid=X&token=Y
    Client->>Backend: POST /api/v1/auth/setup-password/
    activate Backend
    Backend->>Backend: Set password, is_active=True
    Backend->>Backend: Create Company, CompanyMember (L1 = unverified)
    Backend-->>Client: 200 Password set, user active
    deactivate Backend

    Client->>Backend: POST /api/v1/accounts/companies/upload-document/
    activate Backend
    Backend->>Backend: Store document in MinIO (private bucket)
    Backend-->>Client: 201 Document uploaded
    deactivate Backend

    Admin->>Admin: Navigate to KYC Dashboard (/admin/accounts/company/)
    Admin->>Manager: "Review pending KYC docs"

    Manager->>Backend: GET /api/v1/accounts/companies/?verification_status=L1
    Backend-->>Manager: List pending companies with documents

    alt Manager Approves
        Manager->>Backend: POST /api/v1/accounts/companies/{id}/verify-kyc/
        activate Backend
        Backend->>Backend: Set verification_status=L2 (verified)
        Backend->>Email: Send approval email
        Backend-->>Manager: 200 KYC Approved
        deactivate Backend
        Email->>Client: "Your company is now verified (L2)"
    else Manager Rejects
        Manager->>Backend: POST /api/v1/accounts/companies/{id}/reject-kyc/
        activate Backend
        Backend->>Backend: Set verification_status=L1 (rejected)
        Backend->>Email: Send rejection email with feedback
        Backend-->>Manager: 200 KYC Rejected
        deactivate Backend
        Email->>Client: "KYC rejected, please re-submit"
        Client->>Backend: POST /api/v1/accounts/companies/upload-document/
        Backend-->>Client: 201 New document uploaded
    end

    Client->>Client: Now can create deals (verification_status=L2)
```

**Key Points:**
- **L1 Status**: User registered, password set, company created but unverified
- **L2 Status**: Documents approved by KYC manager, full access enabled
- Documents stored in MinIO private bucket with access control
- Email verification happens at registration and KYC milestone stages

---

## 3. Authentication Flow (Sequence Diagram)

JWT-based authentication with automatic token refresh:

```mermaid
sequenceDiagram
    participant Client as Client<br/>(React App)
    participant API as API Client<br/>(Axios + Interceptor)
    participant Backend as Django Backend
    participant Redis as Redis<br/>(Token Blacklist)

    Client->>API: User logs in with email/password

    API->>Backend: POST /api/v1/auth/token/
    activate Backend
    Backend->>Backend: Validate credentials
    Backend->>Redis: Store refresh token hash
    Backend-->>API: 200 {access_token, refresh_token}
    deactivate Backend

    API->>API: Store tokens (access in memory, refresh in localStorage)
    API-->>Client: Login successful, redirect to dashboard

    Note over Client: Access token valid for 30 minutes

    Client->>API: GET /api/v1/catalog/products/
    API->>API: Attach access token to Authorization header

    API->>Backend: GET /api/v1/catalog/products/ (with access token)
    activate Backend
    Backend->>Backend: Verify JWT signature (30min TTL)
    Backend-->>API: 200 Products list
    deactivate Backend

    API-->>Client: Display products

    Note over Client: 30 minutes pass, access token expires

    Client->>API: GET /api/v1/accounts/me/
    API->>API: Attach expired access token

    API->>Backend: GET /api/v1/accounts/me/ (with expired token)
    activate Backend
    Backend->>Backend: JWT verification fails (expired)
    Backend-->>API: 401 Token expired
    deactivate Backend

    API->>API: Interceptor catches 401
    API->>API: Check if refresh token exists

    alt Refresh Token Valid
        API->>Backend: POST /api/v1/auth/token/refresh/ (with refresh token)
        activate Backend
        Backend->>Redis: Check if refresh token not blacklisted
        Backend->>Backend: Verify refresh token (7d TTL)
        Backend->>Redis: Rotate: blacklist old token, issue new pair
        Backend-->>API: 200 {access_token, refresh_token}
        deactivate Backend
        
        API->>API: Update stored tokens
        API->>Backend: Retry original request with new access token
        Backend-->>API: 200 User profile
        API-->>Client: Display user data

    else Refresh Token Expired (>7 days)
        API->>Backend: POST /api/v1/auth/token/refresh/ (with expired refresh token)
        activate Backend
        Backend->>Backend: Verify refresh token fails (expired)
        Backend-->>API: 401 Refresh token expired
        deactivate Backend
        
        API->>API: Clear all stored tokens
        API-->>Client: Redirect to /login page
        Client->>Backend: User must log in again
    end

    Note over API: Token rotation prevents reuse of compromised refresh tokens
```

**Key Points:**
- Access token TTL: 30 minutes
- Refresh token TTL: 7 days
- Token rotation on refresh to prevent replay attacks
- Refresh tokens stored in Redis with blacklist on rotation
- Axios interceptor handles 401 responses automatically

---

## 4. Sourcing & Quote Generation Flow (Sequence Diagram)

Complete workflow from Excel import through quote delivery:

```mermaid
sequenceDiagram
    participant Seller as Seller<br/>(Web)
    participant Backend as Django Backend
    participant Celery as Celery Worker<br/>(Async Task Queue)
    participant PIM as PIM Database<br/>(Products)
    participant RFQ as Manufacturer<br/>(RFQ System)
    participant WeasyPrint as WeasyPrint<br/>(PDF Renderer)
    participant Client as Client<br/>(Email)

    Seller->>Backend: POST /api/v1/sourcing/import-catalog/
    activate Backend
    Backend->>Backend: Create ImportTask(status='PENDING')
    Backend->>Celery: Enqueue process_catalog_import()
    Backend-->>Seller: 202 Import started
    deactivate Backend

    activate Celery
    Celery->>Backend: Read Excel file from MinIO
    Celery->>PIM: Parse products, extract SKU/name/specs
    Celery->>PIM: Smart Match using pg_trgm similarity\n(fuzzy text search)
    
    alt Exact Match Found
        Celery->>PIM: Link to existing Product
    else No Match
        Celery->>PIM: Create new Product in catalog
    end
    
    Celery->>Backend: Update ImportTask(status='COMPLETED')
    deactivate Celery

    Seller->>Backend: GET /api/v1/sourcing/import-status/{task_id}
    Backend-->>Seller: 200 {status: 'COMPLETED', items_imported: 45}

    Note over Seller: Deal created with sourced items

    Seller->>Backend: POST /api/v1/crm/deals/{id}/send-rfq/
    activate Backend
    Backend->>RFQ: Batch RFQ to manufacturers\n(item specs, qty, delivery_date)
    Backend->>Backend: Create RFQRequest records
    Backend-->>Seller: 200 RFQs sent
    deactivate Backend

    par Manufacturer Responses
        RFQ->>Backend: Manufacturer 1 responds with pricing
        RFQ->>Backend: Manufacturer 2 responds with pricing
        RFQ->>Backend: Manufacturer 3 responds with pricing
    end

    Backend->>Backend: Smart Match prices to PIM products\n(via SupplierOffer)

    Seller->>Backend: POST /api/v1/crm/deals/{id}/calculate-quote/
    activate Backend
    Backend->>Backend: Load all QuoteItems from RFQ responses
    Backend->>Backend: For each item: calculate landed cost:
    Note over Backend: FCA_Price<br/>+ Logistics<br/>+ Customs_Duty<br/>+ Margin<br/>+ VAT<br/>= Final_Price
    Backend->>Backend: Create QuoteItemHistory audit trail
    Backend->>Backend: Update Deal.stage to CALCULATING
    Backend-->>Seller: 200 Quote calculated
    deactivate Backend

    Seller->>Backend: POST /api/v1/crm/quotes/generate-pdf/
    activate Backend
    Backend->>Backend: Fetch Quote + QuoteItems + Company branding
    Backend->>WeasyPrint: Render HTML template to PDF
    Backend->>Backend: Store PDF in MinIO (temp bucket)
    Backend-->>Seller: 200 {pdf_url, quote_id}
    deactivate Backend

    Seller->>Backend: POST /api/v1/crm/quotes/send-to-client/
    activate Backend
    Backend->>Backend: Update Quote.status = SENT
    Backend->>Backend: Update Deal.stage = QUOTE_SENT
    Backend->>Client: Send email with PDF + approval link
    Backend-->>Seller: 200 Quote sent to client
    deactivate Backend

    Client->>Backend: GET /approve-quote/{quote_id}/?token=X
    activate Backend
    Backend->>Backend: Verify token
    Backend->>Backend: Update Quote.status = APPROVED
    Backend->>Backend: Update Deal.stage = CONTRACT_SIGNED
    Backend-->>Client: 200 Quote approved, confirmation email sent
    deactivate Backend

    Note over Backend: Deal now in CONTRACT_SIGNED state\nReady for order fulfillment
```

**Key Workflow Steps:**

1. **Excel Import (Celery Task):**
   - Parse product data from Excel
   - Smart Match to PIM using PostgreSQL `pg_trgm` similarity search
   - Create new products or link to existing ones

2. **RFQ & Pricing:**
   - Send RFQ to manufacturers with specifications
   - Collect responses with unit prices
   - Record in SupplierOffer

3. **Quote Calculation:**
   - Load landed cost formula per item:
     - Base price (from manufacturer)
     - Shipping/logistics cost
     - Customs duty
     - Seller margin (configurable)
     - VAT calculation
   - Store all calculations in QuoteItemHistory for audit trail
   - Create financial snapshot (decimal.js precision)

4. **PDF Generation:**
   - Render quote template with company logo
   - Convert to PDF via WeasyPrint
   - Store in MinIO (temp bucket, auto-expire)

5. **Client Approval:**
   - Send secure link to client
   - Client approves/rejects
   - Deal transitions to CONTRACT_SIGNED or CLOSED_LOST

---

## 5. Multi-Tenancy & Company Role Architecture

How the platform handles multiple company types and roles:

```mermaid
graph TB
    subgraph Users["Users & Authentication"]
        CustomUser["CustomUser<br/>(email login)"]
        SystemRole["SystemRole<br/>(ADMIN, MANAGER, CLIENT)"]
    end

    subgraph Company["Company & Multi-Tenancy"]
        Company["Company<br/>(name, type, kyc_status)"]
        CompanyType["CompanyType<br/>(CLIENT, SUPPLIER, MANUFACTURER)"]
        CompanyMember["CompanyMember<br/>(user, company, role)"]
    end

    subgraph CatalogDomain["Catalog & Products (PIM)"]
        Product["Product<br/>(sku, name, specs)"]
        Category["Category<br/>(hierarchy)"]
        SupplierOffer["SupplierOffer<br/>(supplier, product, price)"]
        EquipmentGroup["EquipmentGroup<br/>(standard groups)"]
    end

    subgraph CRMDomain["CRM & Deal Management"]
        Deal["Deal<br/>(status, company_id, stage)"]
        Quote["Quote<br/>(deal_id, total_price, status)"]
        QuoteItem["QuoteItem<br/>(quote_id, product_id, qty, price)"]
        QuoteItemHistory["QuoteItemHistory<br/>(audit trail)"]
        Message["Message<br/>(deal comments)"]
    end

    subgraph SourcingDomain["Sourcing & Imports"]
        ImportTask["ImportTask<br/>(status, file_url)"]
        RFQRequest["RFQRequest<br/>(manufacturer, items)"]
        Attachment["Attachment<br/>(documents)"]
    end

    subgraph MasterData["Master Data & Reference"]
        Country["Country<br/>(code, name)"]
        Currency["Currency<br/>(code, symbol)"]
        UOM["Unit of Measure<br/>(kg, pcs, m, etc)"]
        DeliveryBasis["Delivery Basis<br/>(FCA, CIF, DDP)"]
    end

    CustomUser -->|has| CompanyMember
    CompanyMember -->|belongs to| Company
    Company -->|has types| CompanyType
    CustomUser -->|has role| SystemRole

    Company -->|SUPPLIER| SupplierOffer
    SupplierOffer -->|references| Product

    Deal -->|created by| Company
    Deal -->|has| Quote
    Quote -->|contains| QuoteItem
    QuoteItem -->|references| Product
    QuoteItem -->|tracked by| QuoteItemHistory

    Deal -->|has| Message
    Deal -->|has| RFQRequest
    RFQRequest -->|sent to| Company

    ImportTask -->|imports to| Product
    Attachment -->|supports| Deal

    Product -->|in| Category
    Product -->|in| EquipmentGroup
    Product -->|measured in| UOM
    Deal -->|priced in| Currency
    SupplierOffer -->|from| Country
    Quote -->|delivery via| DeliveryBasis

    style CustomUser fill:#e1f5ff
    style Company fill:#f3e5f5
    style CompanyMember fill:#f3e5f5
    style Deal fill:#e8f5e9
    style Quote fill:#e8f5e9
    style Product fill:#fff3e0
    style SupplierOffer fill:#fff3e0
```

**Multi-Tenancy Model:**
- No schema/database isolation (single-tenant architecture)
- Tenancy via `CompanyMember` join table with `company_id` filtering
- Every API query includes company context from JWT (via `request.user.company`)
- Company types determine UI layout and feature access (BUYER, SELLER, MANUFACTURER)

---

## 6. Frontend State Management & Role-Based Access

How the React frontend manages auth state and role context:

```mermaid
graph TB
    subgraph Browser["Browser (React App)"]
        LoginPage["LoginPage<br/>(email/password entry)"]
        PasswordSetupPage["PasswordSetupPage<br/>(setup-password route)"]
        KYCRegistrationForm["KYCRegistrationForm<br/>(profile + documents)"]
        DashboardPage["DashboardPage<br/>(main SPA)"]
    end

    subgraph Zustand["Zustand Stores<br/>(Client-side State)"]
        AuthStore["authStore<br/>(user, tokens, loggedIn)"]
        UserStore["userStore<br/>(firstName, activeStatus,<br/>kycStatus, companyId)"]
        ThemeStore["themeStore<br/>(dark mode)"]
        CurrencyStore["currencyStore<br/>(selected currency)"]
        DomainStore["domainStore<br/>(Uzbek domain state)"]
    end

    subgraph APIClient["API Client (Axios)"]
        APIInterceptor["JWT Interceptor<br/>(attach token, refresh on 401)"]
        CatalogAPI["catalogApi<br/>(products, offers)"]
        CRMAPI["crmApi<br/>(deals, quotes)"]
        AccountsAPI["accountsApi<br/>(users, companies)"]
    end

    subgraph Layouts["Shell Layouts<br/>(shadcn Sidebar)"]
        AppShell["AppShell<br/>(Buyer/Seller context<br/>hash-based SPA)"]
        AdminShell["AdminShell<br/>(/admin/*, React Router)"]
        ClientShell["ClientShell<br/>(/cabinet/*, React Router)"]
        CatalogShell["CatalogShell<br/>(Public catalog,<br/>no sidebar)"]
    end

    subgraph RoleMapping["Frontend Role Mapping<br/>(from userStore.loadFromAuth)"]
        L1Unverified["L1 (Unverified)<br/>Only profile page"]
        L2Verified["L2 (Verified)<br/>Create deals"]
        BuyerStatus["BUYER Status<br/>(CLIENT company type)<br/>See sourcing dashboard"]
        SellerStatus["SELLER Status<br/>(SUPPLIER company type)<br/>See catalog mgmt + RFQ"]
        ManufacturerStatus["MANUFACTURER Status<br/>(MANUFACTURER type)<br/>Respond to RFQs"]
    end

    LoginPage -->|POST /auth/token/| APIClient
    LoginPage -->|success| AuthStore
    AuthStore -->|tokens stored| Browser

    PasswordSetupPage -->|POST /auth/setup-password/| APIClient
    KYCRegistrationForm -->|POST /auth/submit-profile/| APIClient
    KYCRegistrationForm -->|POST /accounts/companies/upload-document/| APIClient

    AuthStore -->|user data| UserStore
    APIClient -->|GET /accounts/me/| UserStore
    UserStore -->|loadFromAuth()| UserStore
    UserStore -->|maps CompanyType| RoleMapping

    UserStore -->|activeStatus| AppShell
    UserStore -->|activeStatus| AdminShell
    UserStore -->|activeStatus| ClientShell
    UserStore -->|kycStatus| RoleMapping

    RoleMapping -->|L1| AppShell
    RoleMapping -->|L2 + BUYER| DashboardPage
    RoleMapping -->|L2 + SELLER| DashboardPage

    AuthStore -->|access token| APIInterceptor
    APIInterceptor -->|calls| CatalogAPI
    APIInterceptor -->|calls| CRMAPI
    APIInterceptor -->|calls| AccountsAPI

    CatalogAPI -->|products| DashboardPage
    CRMAPI -->|deals, quotes| DashboardPage
    AccountsAPI -->|user, company| DashboardPage

    ThemeStore -->|CSS variables| AppShell
    CurrencyStore -->|decimal.js| DashboardPage
    DomainStore -->|UZ state| DashboardPage

    style AuthStore fill:#e3f2fd
    style UserStore fill:#e3f2fd
    style AppShell fill:#f1f8e9
    style RoleMapping fill:#fff9c4
```

**Frontend Authentication Flow:**

1. **Login**: `LoginPage` → POST `/auth/token/` → get access + refresh tokens
2. **Token Storage**: Access in memory (secure), refresh in localStorage (persistent)
3. **Load User**: `userStore.loadFromAuth()` → GET `/accounts/me/` → maps CompanyType to frontend CompanyStatus
4. **Role Determination**: `userStore.activeStatus` + `kycStatus` determines UI layout and feature access
5. **Token Refresh**: Axios interceptor catches 401, auto-refreshes via POST `/auth/token/refresh/`, retries request
6. **Logout**: Clear tokens, `AuthStore` → `loggedIn=false`, redirect to `/login`

**Store Persistence:**
- `authStore` and `themeStore` use `persist` middleware (localStorage)
- Other stores are ephemeral (cleared on reload)

---

## 7. WebSocket & Real-Time Communication (Channels)

How the backend handles real-time deal updates:

```mermaid
sequenceDiagram
    participant Seller as Seller<br/>(Web)
    participant Frontend as Frontend<br/>(React)
    participant Daphne as Daphne<br/>(ASGI Server)
    participant Channels as Channels<br/>(WebSocket Layer)
    participant Redis as Redis<br/>(Channel Layer)
    participant Celery as Celery<br/>(Task Queue)
    participant Admin as Admin<br/>(KYC Manager)

    Seller->>Frontend: User opens deal page
    Frontend->>Daphne: WebSocket: wss://api.railtech.uz/ws/deals/{deal_id}/
    Daphne->>Channels: New consumer connection
    Channels->>Redis: Subscribe to channel: deals.{deal_id}

    Admin->>Admin: Approve KYC in Django admin
    Admin->>Celery: Trigger deal state change
    Celery->>Redis: Publish to channel: deals.{deal_id}

    Redis->>Channels: Broadcast message to all subscribers
    Channels->>Daphne: Message received
    Daphne->>Frontend: WebSocket message: {event: 'kyc_approved', stage: 'SOURCING'}

    Frontend->>Frontend: Update deal state in Zustand
    Frontend->>Frontend: Re-render UI with new stage

    Note over Seller: Seller sees deal stage update in real-time\n(no page refresh needed)

    Seller->>Daphne: WebSocket: Close connection
    Channels->>Redis: Unsubscribe from channel
```

**WebSocket Setup:**
- Daphne (ASGI) replaces Gunicorn for WebSocket support
- Redis as channel layer (separate from Celery Redis on :6380)
- Consumer logic in `core/consumers.py`
- Broadcast on deal updates (stage change, quote approval, etc.)

---

## 8. Storage Architecture (MinIO & Local Fallback)

File storage and serving strategy:

```mermaid
graph TB
    subgraph Upload["File Upload"]
        Frontend["Frontend<br/>(File input)"]
        Backend["Django Backend<br/>(file view)"]
    end

    subgraph Storage["Storage Backend"]
        MinIOCheck["Check MinIO availability"]
        MinIOSuccess["MinIO Available"]
        MinIOFail["MinIO Down (fallback)"]
        MinIO["MinIO Server<br/>(S3-compatible)<br/>:9000, :9001"]
        LocalFS["Local Filesystem<br/>(media/private, etc)"]
    end

    subgraph Buckets["MinIO Buckets"]
        PublicBucket["public/\n(product images,<br/>logos)"]
        PrivateBucket["private/\n(KYC documents,<br/>quotes)"]
        TempBucket["temp/\n(session files,<br/>auto-expire)"]
    end

    subgraph Serving["File Serving"]
        NginxStatic["Nginx<br/>(static file cache,<br/>rate limiting)"]
        Presigned["S3 Presigned URLs<br/>(temporary access)"]
        DirectDownload["Direct download<br/>(with auth check)"]
    end

    Frontend -->|POST file| Backend
    Backend -->|file data| MinIOCheck

    MinIOCheck -->|healthy| MinIOSuccess
    MinIOCheck -->|timeout/error| MinIOFail

    MinIOSuccess -->|PUT| MinIO
    MinIOFail -->|fallback| LocalFS

    MinIO -->|buckets| PublicBucket
    MinIO -->|buckets| PrivateBucket
    MinIO -->|buckets| TempBucket

    LocalFS -->|stores| PublicBucket
    LocalFS -->|stores| PrivateBucket
    LocalFS -->|stores| TempBucket

    PublicBucket -->|GET| NginxStatic
    PrivateBucket -->|signed URL| Presigned
    TempBucket -->|direct| DirectDownload

    NginxStatic -->|cache hit| Frontend
    Presigned -->|temporary access| Frontend
    DirectDownload -->|auth validated| Frontend

    style MinIO fill:#ffe0b2
    style LocalFS fill:#ffccbc
    style Presigned fill:#c8e6c9
```

**Bucket Strategy:**
- **public/**: Product images, company logos (cached by Nginx, no auth)
- **private/**: KYC documents, quotes, contracts (presigned URLs with 1h expiry)
- **temp/**: Session uploads, temporary files (auto-delete after 7 days)

**Fallback:**
- If MinIO unavailable → write to local filesystem (`/app/media/`)
- Avoids request blocking on storage failure

---

## 9. CI/CD Pipeline (GitHub Actions)

Automated testing, linting, and deployment:

```mermaid
graph LR
    subgraph Commit["Code Pushed to GitHub"]
        Push["Push to main/dev"]
    end

    subgraph CI["GitHub Actions Jobs<br/>(run in parallel)"]
        BackendLint["Backend Lint<br/>(flake8, black, isort)"]
        BackendTest["Backend Test<br/>(pytest, 50% coverage)"]
        FrontendLint["Frontend Lint<br/>(eslint)"]
        FrontendBuild["Frontend Build<br/>(Vite)"]
        DockerBuild["Docker Build<br/>(docker-compose up --build)"]
        Security["Security Check<br/>(bandit, npm audit)"]
    end

    subgraph Checks["Check Results"]
        Success["All checks pass ✓"]
        Failure["One or more fail ✗"]
    end

    subgraph Artifact["Build Artifacts"]
        DockerImage["Docker image<br/>(backend, frontend)"]
        CoverageReport["Coverage report"]
        BuildLog["Build log"]
    end

    subgraph Deploy["Deployment<br/>(Manual or Auto)"]
        Manual["Manual approval<br/>(trigger deploy)"]
        AutoDeploy["Auto-deploy on main<br/>(to staging/prod)"]
    end

    Push -->|triggers| BackendLint
    Push -->|triggers| BackendTest
    Push -->|triggers| FrontendLint
    Push -->|triggers| FrontendBuild
    Push -->|triggers| DockerBuild
    Push -->|triggers| Security

    BackendLint -->|report| Checks
    BackendTest -->|report| Checks
    FrontendLint -->|report| Checks
    FrontendBuild -->|report| Checks
    DockerBuild -->|report| Checks
    Security -->|report| Checks

    Success -->|artifacts| Artifact
    Failure -->|block| Deploy

    DockerImage -->|push to registry| Deploy
    CoverageReport -->|log| Deploy

    Deploy -->|dev branch| Manual
    Deploy -->|main branch| AutoDeploy

    AutoDeploy -->|docker pull| Staging
    AutoDeploy -->|docker pull| Production

    style Success fill:#c8e6c9
    style Failure fill:#ffcdd2
    style AutoDeploy fill:#bbdefb
```

**Pipeline Summary:**
- 6 parallel jobs (linting, testing, building)
- Blocks deployment on failure
- Artifacts: Docker images, coverage reports, build logs
- Auto-deploy on `main`, manual approval on `dev`

---

## 10. Error Handling & Observability

Request lifecycle with error handling:

```mermaid
sequenceDiagram
    participant Client as Client<br/>(Web)
    participant Frontend as Frontend<br/>(React)
    participant APIGateway as API Gateway<br/>(Nginx)
    participant Backend as Backend<br/>(Django)
    participant Database as PostgreSQL
    participant Redis as Redis
    participant ErrorLog as Error Log<br/>(Sentry/Logs)

    Client->>Frontend: User triggers action
    Frontend->>APIGateway: HTTP request with JWT

    APIGateway->>APIGateway: Rate limit check
    APIGateway->>APIGateway: CORS check
    APIGateway->>Backend: Forward request

    Backend->>Backend: Parse request, validate JWT
    Backend->>Database: Query database

    alt Success Path
        Database-->>Backend: Data returned
        Backend->>Backend: Serialize response
        Backend-->>APIGateway: 200 OK + JSON
        APIGateway-->>Frontend: Response
        Frontend->>Frontend: Update Zustand store
        Frontend->>Frontend: Show success toast
        Frontend-->>Client: Display data
    
    else Database Error
        Database-->>Backend: Connection timeout / 500 error
        Backend->>ErrorLog: Log exception (Sentry)
        Backend->>Redis: Cache fallback (if available)
        alt Cache Hit
            Redis-->>Backend: Stale data
            Backend-->>APIGateway: 200 OK + stale_data warning
        else Cache Miss
            Backend-->>APIGateway: 503 Service Unavailable
        end
        APIGateway-->>Frontend: 503 response
        Frontend->>Frontend: Show error toast
        Frontend-->>Client: "Service temporarily unavailable"
    
    else Validation Error
        Backend->>Backend: Input validation fails
        Backend->>ErrorLog: Log validation error
        Backend-->>APIGateway: 400 Bad Request + field_errors
        APIGateway-->>Frontend: 400 response
        Frontend->>Frontend: Show field errors
        Frontend-->>Client: Highlight invalid fields
    
    else Authorization Error
        Backend->>Backend: User lacks permission
        Backend->>ErrorLog: Log permission denial
        Backend-->>APIGateway: 403 Forbidden
        APIGateway-->>Frontend: 403 response
        Frontend->>Frontend: Show "access denied" toast
        Frontend-->>Client: Disable feature UI
    
    else Authentication Error
        Backend->>Backend: Token expired / invalid
        Backend-->>APIGateway: 401 Unauthorized
        APIGateway-->>Frontend: 401 response
        Frontend->>Frontend: Attempt token refresh
        Frontend->>Backend: POST /auth/token/refresh/
        Backend-->>Frontend: New token or 401
        alt Refresh Success
            Frontend->>Frontend: Retry original request
        else Refresh Failed
            Frontend->>Frontend: Logout, redirect to /login
        end
    end
```

**Error Handling Layers:**

1. **Frontend (React):**
   - Axios interceptor catches HTTP errors
   - Toast notifications for user-facing errors
   - Form field validation before submit
   - Loading states during requests

2. **Backend (Django):**
   - Input validation via serializers
   - Permission checks via DRF permissions
   - Database transaction rollback on error
   - Logging to Sentry (if configured)
   - Structured error responses with field details

3. **Infrastructure (Nginx):**
   - Rate limiting (per IP, per user)
   - CORS validation
   - Static file caching
   - Upstream health checks

---

## Document Metadata

- **Last Updated**: 2026-04-17
- **Version**: 1.1
- **Author**: RailTech Architecture Team
- **Audience**: Engineers, Architects, DevOps, PMs

For detailed implementation specifics, see:

- [technical-specification.md](technical-specification.md) — API endpoints, schemas
- [business-logic.md](business-logic.md) — Deal FSM, quote calculation
- [interface-architecture.md](interface-architecture.md) — Frontend component architecture
- [docker-setup.md](docker-setup.md) — Container orchestration guide
- [websocket-messages.md](websocket-messages.md) — WebSocket protocol
