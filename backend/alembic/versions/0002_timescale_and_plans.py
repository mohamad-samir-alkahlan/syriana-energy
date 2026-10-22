"""TimescaleDB hypertable (if available) + seed plans

Revision ID: 0002
Revises: 0001
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ALL = ["control", "ai", "email", "webhook", "automations", "api", "white_label", "customers"]
HOME = ["control", "ai", "email", "webhook", "automations", "api"]
PLANS = [
    ("free", "Free", "مجاني", 0.0, 0.0, 1, 7, [], False, 0),
    ("home", "Home", "بيت", 4.0, 40.0, 3, 365, HOME, False, 1),
    ("pro", "Pro", "احترافي", 9.0, 90.0, 10, 730, HOME, False, 2),
    ("installer", "Installer", "مُركِّب", 2.0, 20.0, 500, 730, ALL, True, 3),
]


def upgrade() -> None:
    conn = op.get_bind()
    # Hypertable only when TimescaleDB is installed; otherwise a plain table with PK (device_id, ts).
    avail = conn.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name='timescaledb'")).scalar()
    if avail:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        conn.execute(sa.text(
            "SELECT create_hypertable('readings','ts', chunk_time_interval => INTERVAL '7 days', "
            "if_not_exists => TRUE, migrate_data => TRUE)"))
    for code, name, name_ar, pm, py, md, hd, feats, per_dev, sort in PLANS:
        conn.execute(
            sa.text(
                "INSERT INTO plans (code,name,name_ar,price_month,price_year,currency,max_devices,history_days,"
                "features,per_device,sort) VALUES (:c,:n,:na,:pm,:py,'USD',:md,:hd,CAST(:f AS jsonb),:pd,:s) "
                "ON CONFLICT (code) DO NOTHING"),
            dict(c=code, n=name, na=name_ar, pm=pm, py=py, md=md, hd=hd, f=json.dumps(feats), pd=per_dev, s=sort))


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM plans WHERE code IN ('free','home','pro','installer')"))
