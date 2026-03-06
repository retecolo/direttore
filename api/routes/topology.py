from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.db import get_db
from api.models import Topology, TopologyNode, TopologyEdge
from api.schemas.topology import TopologyCreate, TopologyRead, TopologyList

router = APIRouter(prefix="/api/topology", tags=["topology"])

@router.get("/", response_model=List[TopologyList])
async def list_topologies(db: AsyncSession = Depends(get_db)):
    """List all saved topologies."""
    result = await db.execute(select(Topology).order_by(Topology.updated_at.desc()))
    return result.scalars().all()

@router.get("/{topology_id}", response_model=TopologyRead)
async def get_topology(topology_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch a specific topology with all its nodes and edges."""
    stmt = (
        select(Topology)
        .where(Topology.id == topology_id)
        .options(selectinload(Topology.nodes), selectinload(Topology.edges))
    )
    result = await db.execute(stmt)
    topology = result.scalars().first()
    if not topology:
        raise HTTPException(status_code=404, detail="Topology not found")
    return topology

@router.post("/", response_model=TopologyRead)
async def save_topology(body: TopologyCreate, db: AsyncSession = Depends(get_db)):
    """Create or update a topology with automatic resource preservation."""
    # Find existing default topology
    result = await db.execute(select(Topology).limit(1))
    topology = result.scalars().first()

    if not topology:
        topology = Topology(name=body.name, description=body.description)
        db.add(topology)
        await db.flush()
    else:
        topology.name = body.name
        topology.description = body.description
        # Explicitly delete old children to prevent lazy-loading crashes during mutation
        await db.execute(delete(TopologyNode).where(TopologyNode.topology_id == topology.id))
        await db.execute(delete(TopologyEdge).where(TopologyEdge.topology_id == topology.id))
        
    # Add new nodes
    for n in body.nodes:
        db.add(TopologyNode(
            id=n.id,
            topology_id=topology.id,
            pos_x=n.pos_x,
            pos_y=n.pos_y,
            data=n.data,
            type=n.type
        ))

    # Add new edges
    for e in body.edges:
        db.add(TopologyEdge(
            id=e.id,
            topology_id=topology.id,
            source=e.source,
            target=e.target,
            source_handle=e.source_handle,
            target_handle=e.target_handle,
            data=e.data
        ))

    await db.commit()
    
    # Reload with all relationships for response
    stmt = (
        select(Topology)
        .where(Topology.id == topology.id)
        .options(selectinload(Topology.nodes), selectinload(Topology.edges))
    )
    result = await db.execute(stmt)
    return result.scalars().first()

@router.delete("/{topology_id}", status_code=204)
async def delete_topology(topology_id: int, db: AsyncSession = Depends(get_db)):
    topology = await db.get(Topology, topology_id)
    if not topology:
        raise HTTPException(status_code=404, detail="Topology not found")
    await db.delete(topology)
    await db.commit()
