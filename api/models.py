"""SQLAlchemy ORM models for Direttore."""

import datetime
from sqlalchemy import DateTime, Integer, String, Float, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.db import Base
import enum
from typing import List, Optional


class ResourceType(str, enum.Enum):
    vm = "vm"
    lxc = "lxc"


class ReservationStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    requester: Mapped[str] = mapped_column(String(64), nullable=False, default="anonymous")
    resource_type: Mapped[ResourceType] = mapped_column(
        SAEnum(ResourceType), nullable=False, default=ResourceType.vm
    )
    proxmox_node: Mapped[str] = mapped_column(String(64), nullable=True)
    vmid: Mapped[int] = mapped_column(Integer, nullable=True)
    start_dt: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    end_dt: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        SAEnum(ReservationStatus), nullable=False, default=ReservationStatus.pending
    )
    notes: Mapped[str] = mapped_column(String(512), nullable=True)


class ResourcePool(Base):
    __tablename__ = "resource_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    proxmox_node: Mapped[str] = mapped_column(String(64), nullable=False)
    max_vms: Mapped[int] = mapped_column(Integer, default=10)
    max_lxc: Mapped[int] = mapped_column(Integer, default=20)


class Topology(Base):
    __tablename__ = "topologies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="Default Lab")
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.datetime.now(datetime.timezone.utc), 
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    nodes: Mapped[List["TopologyNode"]] = relationship(
        "TopologyNode", back_populates="topology", cascade="all, delete-orphan", lazy="selectin"
    )
    edges: Mapped[List["TopologyEdge"]] = relationship(
        "TopologyEdge", back_populates="topology", cascade="all, delete-orphan", lazy="selectin"
    )


class TopologyNode(Base):
    __tablename__ = "topology_nodes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # React Flow node ID
    topology_id: Mapped[int] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    
    # Position
    pos_x: Mapped[float] = mapped_column(Float, nullable=False)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Resource Data (stored as JSON for flexibility)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="resource")

    topology: Mapped["Topology"] = relationship("Topology", back_populates="nodes")


class TopologyEdge(Base):
    __tablename__ = "topology_edges"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # React Flow edge ID
    topology_id: Mapped[int] = mapped_column(ForeignKey("topologies.id"), nullable=False)
    
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    source_handle: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_handle: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    # Extra properties (style, label, etc.)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    topology: Mapped["Topology"] = relationship("Topology", back_populates="edges")
