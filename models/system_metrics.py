# app/models/system_metrics.py

from sqlalchemy import Column, Integer, String, Text, Float, DateTime
from datetime import datetime
from app.core.database import Base


class SystemMetrics(Base):
    __tablename__ = "system_metrics"

    metric_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Metric data
    metric_type = Column(String(100), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    description = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<SystemMetrics id={self.metric_id} "
            f"type={self.metric_type} "
            f"value={self.metric_value} "
            f"at={self.timestamp}>"
        )