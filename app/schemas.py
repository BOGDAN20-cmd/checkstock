from pydantic import BaseModel, Field
from typing import Optional

class MovementCreate(BaseModel):
    product_id: int
    type: str = Field(..., pattern="^(receipt|shipment|transfer)$")
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: int = Field(..., gt=0)

class StockResponse(BaseModel):
    id: int
    product_name: str
    warehouse_name: str
    quantity: int

    class Config:
        from_attributes = True
