# Implementation contract

Python 3.13+, Django 5.2 LTS, PostgreSQL/Neon; SQLite local development only. Server templates + vanilla JS. Spanish UX. App `portal`, project `config`.

## Models (core agent owns)
- User(AbstractUser): email unique, phone, contact_preference whatsapp/call/email, advertiser_status pending/approved/rejected/suspended, email_verified bool, company, marketing_consent, is_test. username stores normalized email. Roles via groups and Django permissions.
- Category: name, slug unique, fields JSON list, active bool.
- Machine: UUID id, owner FK User, title default Mi maquinaria, category FK nullable, data JSON dictionary (brand/model/year/serial/hours/description/location/price/currency/condition/notes/contact_public), provenance JSON dictionary field->{source,review,asset_id}, revision int default 1; status draft/submitted/in_review/changes_requested/approved/rejected/cancelled; availability available/reserved/sold/withdrawn; approved_version FK MachineVersion nullable, created_at/updated_at. folio property IMC-<id prefix>. editable property.
- MachineVersion: machine, number, data JSON full snapshot (title/category/data/provenance/asset_ids), created_by, created_at. Immutable.
- Asset: UUID id, machine FK related assets, revision int, original FileField, preview FileField nullable, kind image/video, purpose general/plate/detail/document, mime_type, size, sha256, position, is_cover, public_authorized default false, processing_status ready/pending/failed, error, created_at. File fields private storage; no public MEDIA route.
- Submission: machine, version, status same as machine, message, decided_by nullable, decided_at nullable, created_at. related submissions.
- Publication: machine, version nullable, destination share/main, status unpublished/approved/exported/published/failed/disabled, token UUID, enabled false, external_id/url, last_error, updated_at.
- Message: machine, sender, body, internal bool default false, created_at. related messages.
- Consent: user, machine nullable, kind terms/privacy/ai/advertise/contact/marketing, version default 2026-09, granted bool, created_at.
- AnalysisJob: UUID id, machine, revision, requested_by, asset_ids JSON list of strings, mode analysis/description, fingerprint unique, status queued/running/completed/failed, attempts, result JSON, error, model, prompt_version, input_tokens/output_tokens, reserved_tokens, locked_at nullable, started_at nullable, finished_at nullable, created_at.
- AuditEvent: actor nullable, action, object_type, object_id, metadata JSON, created_at.
- Lead: name,email,phone,message,machine nullable, user nullable, assigned_to nullable, priority low/normal/high, status new/contacted/qualified/closed, next_action_at nullable, internal_notes, is_test, created_at.
- Notification: user, machine nullable, kind, subject, body, channel in_app/email, status pending/sent/failed, error, attempts, created_at/sent_at.
- SiteContent: key unique, title, body, active; safe plain text only.
- PlatformSettings(singleton pk=1): ai_enabled, max_images=20, max_image_mb=20, max_video_mb=100, max_video_seconds=120, ai_user_daily_limit=10, ai_global_daily_limit=100, ai_daily_token_limit=200000, ai_max_attempts=2, legal_validated=false, contact_email, contact_phone, retention_days=365.
- AnalyticsEvent: event, user nullable, machine nullable, session_hash, source/campaign/device, is_test, created_at. No raw IP.

## Core services contract
`save_draft(machine,user,payload,expected_revision)` returns Machine locked/version increment; validates whitelist; optimistic conflict raises ValidationError. `snapshot(machine,user)` returns MachineVersion. `submit_machine(machine,user,advertise_consent,contact_consent=False)` requires useful ready image,title,location, consent; returns Submission. `review_submission(submission,actor,decision,reason='')` decision in_review/changes_requested/approved/rejected/cancelled; atomic, audit, version immutability, advertiser approval required for approval. `set_availability(machine,user,value)`; `duplicate_machine(machine,user)` new draft private assets copied safely; `set_advertiser_status(user,actor,status,reason)`; `audit(actor,action,obj,metadata=None)`.

## Routes & templates (root owns views/forms/routes)
home /, public page /<slug>/ -> portal/page.html {title, intro, sections}; register/login/recovery -> portal/auth.html {form,title,submit_label}; panel -> portal/dashboard.html {machines,counts,recent_messages}; machines list -> portal/machines.html {machines}; wizard /panel/maquinarias/<uuid>/ -> portal/wizard.html {machine,assets,categories,step 1..5,job,data,provenance,machine_json}; detail /panel/maquinarias/<uuid>/ficha/ -> portal/sheet.html {machine,data,assets,public,version}; requests -> portal/requests.html {submissions}; messages -> portal/messages.html {messages_list,machines}; profile -> portal/profile.html {form}; admin Django /admin/ plus custom /operaciones/ -> portal/operations.html {counts,submissions,jobs,leads}; review /operaciones/solicitudes/<int>/ -> portal/review.html {submission,machine,assets,data,provenance,versions,messages_list}; public share /ficha/<uuid>/; contact -> portal/contact.html {form}.

Use literal URL paths in templates for simplicity. Names: home,login,register,logout,panel,machines,machine_create,machine_wizard,machine_sheet,requests_list,messages_list,profile,operations,review,asset_download,public_sheet.

## JSON endpoints (root owns)
POST /api/maquinarias/ creates draft -> {id,url}; POST /api/maquinarias/<uuid>/guardar/ {revision,title,category,data,provenance} -> {revision,saved_at}; POST /api/maquinarias/<uuid>/archivos/ multipart file,purpose -> {id,url,kind,purpose,processing_status}; POST /api/archivos/<uuid>/accion/ {action:delete/cover/up/down,purpose?}; POST /api/maquinarias/<uuid>/analizar/ {consent:true,asset_ids:[],mode:'analysis'} -> {id,status}; GET /api/analisis/<uuid>/ -> {status,result,error}; POST /api/maquinarias/<uuid>/aplicar/ {job_id,fields:[]} explicit acceptance; POST /api/maquinarias/<uuid>/enviar/ {advertise_consent:true,contact_consent:false} -> {folio,status,url}; POST /api/maquinarias/<uuid>/accion/ {action:duplicate/availability,value}; private media /archivos/<uuid>/?original=1 authenticated; public media /ficha/<token>/archivo/<uuid>/ strictly version allowlist; pdf /panel/maquinarias/<uuid>/pdf/ and /ficha/<token>/pdf/.

All mutations CSRF, authentication ownership server checks. JSON error {error,fields?}, no secrets. Browser uses csrf cookie. No optimistic fake success. Normal forms server validation. Versions preserve authorized asset ids. Main portal is export only.

## Processing agent APIs
`portal.processing.ingest_asset(machine,user,uploaded,purpose='general') -> Asset`; `enqueue_analysis(machine,user,asset_ids=None,mode='analysis')->AnalysisJob`; `process_next_job()->bool`; `process_analysis(job)`; `process_notifications()->int`; worker command `python manage.py runworker`; `portal.pdf.build_pdf(machine,data,assets,public=False,version=None)->bytes`.
`portal.storage.PrivateStorage` supports local persistent MEDIA_ROOT or S3 via env; originals always private. Root provides storage settings/environment.

## Ownership
Core agent: portal/models.py, services.py, admin.py, apps.py, migrations/, management/commands/seed.py, tests/test_workflow.py.
Frontend agent: portal/templates/, portal/static/ only. Inspect official public site and document in docs/reference-review.md. No fake inventory/testimonials. Need strong editorial industrial aesthetic navy/red/offwhite.
Processing agent: processing.py, pdf.py, storage.py, management/commands/runworker.py, tests/test_processing.py, docs/processing.md.
Root: config/, manage.py, forms/views/urls/auth, requirements, deployment, integration, remaining tests.
