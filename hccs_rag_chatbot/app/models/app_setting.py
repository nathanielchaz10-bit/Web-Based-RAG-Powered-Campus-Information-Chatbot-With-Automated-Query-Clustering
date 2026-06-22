# app/models/app_setting.py

from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime

from app.core.database import Base


class AppSetting(Base):
    """A single admin-editable configuration value, stored as a string.

    Backs the Portal Settings page: each adjustable parameter (rate-limit
    threshold, RAG temperature, contact email, ...) is one row keyed by a stable
    public name. Values are kept as TEXT and cast on read by ``settings_store``
    against a typed spec, so this table stays schema-stable as parameters come
    and go. Rows are sparse — a key is present only once an admin overrides its
    built-in default.
    """

    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AppSetting key={self.key!r} value={self.value!r}>"
