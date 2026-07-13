# PartsBin API contract (v1)

All routes under `/api`, JSON, session-cookie auth (Flask-Login). Errors: `{"error": "msg"}` + 4xx/5xx.
List endpoints return `{"items": [...], "total": n, "page": p, "per_page": k}` and accept
`?page=&per_page=&sort=&order=`.

## Auth (identical to GarmentGallery2)
POST /api/auth/register {username,email,password,invite_code} ; POST /api/auth/login
{username,password} → {totp_required} or user ; POST /api/auth/verify-totp {code} ;
POST /api/auth/logout ; GET /api/auth/me ; GET /api/auth/setup-totp ; POST /api/auth/enable-totp
{code} ; POST /api/auth/disable-totp {password} ; passkey routes: GET
/api/auth/passkey/register/options, POST /api/auth/passkey/register/verify, POST
/api/auth/passkey/auth/options, POST /api/auth/passkey/auth/verify, GET/DELETE/PUT
/api/auth/passkeys[/<id>]. Admin invitations: GET/POST /api/admin/invitations, DELETE
/api/admin/invitations/<id>.

## Components
GET /api/components?search=&category=&tag=&location=&low_stock=1&out_of_stock=1
GET /api/components/<id>  → component + recent transactions + used_in projects
POST /api/components  {name, category, specs{}, manufacturer, mpn, description, qty_on_hand,
  min_qty, location, datasheet_url, notes, tags[]}
PUT /api/components/<id> ; DELETE /api/components/<id>
POST /api/components/<id>/adjust {delta, note}          # manual stock ±, creates transaction
POST /api/components/<id>/image (multipart) ; GET /uploads/components/<file>
GET /api/components/<id>/transactions
GET /api/categories                                       # fixed seeded list
GET /api/locations                                        # distinct location strings
GET /api/tags ; POST /api/tags {name}

## Projects
GET /api/projects?search=&status=&tag=
GET /api/projects/<id>   → project + bom (each line: component summary, qty_planned, qty_used,
  available, short:bool) + files
POST /api/projects {name, status, description, readme_md, repo_url, tags[]}
PUT /api/projects/<id> ; DELETE /api/projects/<id>
POST /api/projects/<id>/bom {component_id, qty_planned, note} ; PUT/DELETE /api/projects/<id>/bom/<line_id>
POST /api/projects/<id>/bom/<line_id>/consume {qty}       # decrements stock (project_use txn)
POST /api/projects/<id>/files (multipart, kind=image|pdf|schematic|firmware|other)
DELETE /api/projects/<id>/files/<file_id> ; GET /uploads/projects/<file>

## Orders / review queue
GET /api/orders?status=&vendor=
GET /api/orders/<id>  → order + items (+ suggested/confirmed component summaries)
PUT /api/orders/<id> {status, tracking_no, carrier, notes}   # manual edits allowed
POST /api/orders  (manual order entry, same shape as parsed)
PUT /api/orders/<id>/items/<item_id> {component_id | match_status: confirmed|ignored}
POST /api/orders/<id>/items/<item_id>/create-component {overrides...}  # new component from item, auto-confirms
POST /api/orders/<id>/receive    # order → received; each confirmed item: +qty transaction
GET /api/review/pending          # count + items across orders needing match/receive

## Ingest / OAuth
GET /api/ingest/status           # per gmail account: email, token ok/dead/missing, last poll, last error, counts
POST /api/ingest/run             # manual trigger (admin)
GET /api/oauth/login/<user>?key= ; GET /api/oauth/callback   # Google OAuth (key = INGEST_KEY, no session needed)

## Dashboard
GET /api/dashboard  → {low_stock:[component…], out_of_stock:[…], pending_review:n,
  recent_orders:[…], ingest:[account status…], totals:{components, projects, orders}}
