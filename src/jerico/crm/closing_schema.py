"""Tablas aditivas de la spec 004 (paquete de cierre, contrato, firma, buzones, idempotencia).

Se crean con `IF NOT EXISTS` en cada apertura (como el resto del DDL) y NO suben `schema_version`:
una imagen anterior sigue abriendo la base y simplemente ignora estas tablas, lo que permite
revertir el despliegue sin migración inversa. Decisión de diseño documentada en
`specs/004-crm-cierre-contrato-firma/plan.md`."""

CLOSING_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS crm_offers (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  version INTEGER NOT NULL,
  currency TEXT NOT NULL,
  payment_terms TEXT NOT NULL,
  valid_until TEXT,
  special_conditions TEXT,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (lead_id, version)
)""",
    """CREATE TABLE IF NOT EXISTS crm_offer_lines (
  offer_id INTEGER NOT NULL REFERENCES crm_offers(id),
  position INTEGER NOT NULL,
  description TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
  PRIMARY KEY (offer_id, position)
)""",
    """CREATE TABLE IF NOT EXISTS crm_packages (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  version INTEGER NOT NULL,
  offer_id INTEGER NOT NULL REFERENCES crm_offers(id),
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','confirmed','sent','superseded','cancelled')),
  legal_basis TEXT NOT NULL,
  created_by INTEGER NOT NULL,
  confirmed_by INTEGER,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  UNIQUE (lead_id, version)
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_packages_live ON crm_packages (lead_id) "
    "WHERE status IN ('draft','confirmed','sent')",
    """CREATE TABLE IF NOT EXISTS crm_contracts (
  id INTEGER PRIMARY KEY,
  package_id INTEGER NOT NULL REFERENCES crm_packages(id),
  status TEXT NOT NULL CHECK (status IN (
    'package_sent','contract_uploaded','approved_for_signature','sent_for_signature',
    'signed','declined','expired','cancelled','special_form'
  )),
  file_path TEXT,
  sha256 TEXT,
  uploaded_by INTEGER,
  approved_by INTEGER,
  return_reason TEXT,
  expires_at TEXT,
  signed_at TEXT,
  created_at TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_contracts_live ON crm_contracts (package_id) "
    "WHERE status NOT IN ('declined','expired','cancelled')",
    """CREATE TABLE IF NOT EXISTS crm_signatures (
  id INTEGER PRIMARY KEY,
  contract_id INTEGER NOT NULL REFERENCES crm_contracts(id),
  provider TEXT NOT NULL,
  external_id TEXT,
  status TEXT NOT NULL,
  evidence_path TEXT,
  evidence_sha256 TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS crm_idempotency (
  key TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS crm_mailboxes (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES crm_users(id),
  address TEXT NOT NULL,
  secret_env TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  last_ok_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_mail_candidates (
  id INTEGER PRIMARY KEY,
  mailbox_id INTEGER NOT NULL REFERENCES crm_mailboxes(id),
  message_id TEXT NOT NULL,
  sender_email TEXT NOT NULL,
  sender_name TEXT,
  subject TEXT,
  received_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','registered','discarded')),
  lead_id INTEGER,
  expires_at TEXT NOT NULL,
  UNIQUE (mailbox_id, message_id)
)""",
)
