"""Custom reports — tabular reports a group designs, runs on demand and schedules.

A report has a row entity (trip, event, vehicle …), columns (the entity's
fields, Analytics measures and Expressions) with title / sort / decimals /
conditional colours, parameters the person running it fills in (some
required), column filters (e.g. Max speed > 120), and a file format. Every
run — on demand or scheduled — is kept in its history with the file.
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base
from app.models import get_uuid_column


def _group():
    return Column(UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True)


class CustomReportCategory(Base):
    __tablename__ = "custom_report_categories"

    id           = get_uuid_column()
    usergroup_id = _group()
    name         = Column(String(120), nullable=False)


class CustomReport(Base):
    __tablename__ = "custom_reports"

    id             = get_uuid_column()
    usergroup_id   = _group()
    category_id    = Column(UUID(as_uuid=True), ForeignKey("custom_report_categories.id", ondelete="SET NULL"), nullable=True)
    title          = Column(String(160), nullable=False)
    description    = Column(Text, nullable=True)
    row_entity     = Column(String(40), nullable=False)          # custom_reports_service.ENTITIES
    top_n          = Column(Integer, nullable=True)
    columns        = Column(JSON, nullable=False, default=list)  # [{key, title?, sort?, decimals?, show_unit, format?}]
    parameters     = Column(JSON, nullable=False, default=list)  # [{key, required}]
    column_filters = Column(JSON, nullable=False, default=list)  # [{column, op, required}]
    file           = Column(JSON, nullable=False, default=dict)  # {format, csv_separator, orientation, include_parameters}
    created_by     = Column(UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class CustomReportRun(Base):
    """One generated file of a report (on demand, or by a schedule)."""
    __tablename__ = "custom_report_runs"

    id           = get_uuid_column()
    usergroup_id = _group()
    report_id    = Column(UUID(as_uuid=True), ForeignKey("custom_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id  = Column(UUID(as_uuid=True), ForeignKey("report_schedules.id", ondelete="SET NULL"), nullable=True)
    created_by   = Column(String(255), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    parameters   = Column(JSON, nullable=False, default=dict)    # the values used, as text for the history
    status       = Column(String(20), nullable=False, default="done")   # done | failed
    error        = Column(Text, nullable=True)
    rows         = Column(Integer, nullable=True)
    file_name    = Column(String(200), nullable=True)
    mime         = Column(String(100), nullable=True)
    content      = Column(LargeBinary, nullable=True)
    size_bytes   = Column(Integer, nullable=True)
