from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict

class TopologyNodeSchema(BaseModel):
    id: str
    pos_x: float
    pos_y: float
    data: Dict[str, Any]
    type: str = "resource"
    
    model_config = ConfigDict(from_attributes=True)

class TopologyEdgeSchema(BaseModel):
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)

class TopologyBase(BaseModel):
    name: str = "Default Lab"
    description: Optional[str] = None

class TopologyCreate(TopologyBase):
    nodes: List[TopologyNodeSchema] = []
    edges: List[TopologyEdgeSchema] = []

class TopologyUpdate(TopologyBase):
    nodes: Optional[List[TopologyNodeSchema]] = None
    edges: Optional[List[TopologyEdgeSchema]] = None

class TopologyRead(TopologyBase):
    id: int
    created_at: datetime
    updated_at: datetime
    nodes: List[TopologyNodeSchema]
    edges: List[TopologyEdgeSchema]

    model_config = ConfigDict(from_attributes=True)

class TopologyList(TopologyBase):
    id: int
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
