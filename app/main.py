from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app.database import get_db, engine, Base
from app import models, schemas
import os
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаем таблицы при старте (для простоты вместо миграций)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(lifespan=lifespan, title="CheckStock")
templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Эндпоинт для получения остатков
@app.get("/api/stocks")
async def get_stocks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Stock)
        .options(joinedload(models.Stock.product), joinedload(models.Stock.warehouse))
    )
    stocks = result.scalars().all()
    return [
        {
            "id": s.id,
            "product_name": s.product.name,
            "warehouse_name": s.warehouse.name,
            "quantity": s.quantity
        } for s in stocks
    ]

# Эндпоинт для создания движения
@app.post("/api/movements")
async def create_movement(movement: schemas.MovementCreate, db: AsyncSession = Depends(get_db)):
    # 1. Если это отгрузка или перемещение - проверяем остаток на складе-источнике
    if movement.type in ["shipment", "transfer"]:
        if not movement.from_warehouse_id:
            raise HTTPException(status_code=400, detail="Не указан склад списания")
        
        # Блокируем строку остатка (защита от двойного списания)
        result = await db.execute(
            select(models.Stock)
            .where(
                models.Stock.product_id == movement.product_id,
                models.Stock.warehouse_id == movement.from_warehouse_id
            ).with_for_update()
        )
        stock_from = result.scalar_one_or_none()
        
        if not stock_from or stock_from.quantity < movement.quantity:
            raise HTTPException(status_code=400, detail="Недостаточно товара на складе")
        
        stock_from.quantity -= movement.quantity

    # 2. Если это приход или перемещение - добавляем на склад-получатель
    if movement.type in ["receipt", "transfer"]:
        if not movement.to_warehouse_id:
            raise HTTPException(status_code=400, detail="Не указан склад получения")
            
        result = await db.execute(
            select(models.Stock)
            .where(
                models.Stock.product_id == movement.product_id,
                models.Stock.warehouse_id == movement.to_warehouse_id
            ).with_for_update()
        )
        stock_to = result.scalar_one_or_none()
        
        if not stock_to:
            stock_to = models.Stock(product_id=movement.product_id, warehouse_id=movement.to_warehouse_id, quantity=0)
            db.add(stock_to)
            await db.flush() # чтобы получить id
        
        stock_to.quantity += movement.quantity

    # 3. Сохраняем движение
    db_movement = models.Movement(**movement.model_dump())
    db.add(db_movement)
    
    await db.commit()
    return {"status": "ok", "message": "Движение успешно создано"}

# Эндпоинт для получения истории движений
@app.get("/api/movements")
async def get_movements(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Movement)
        .options(joinedload(models.Movement.product))
        .order_by(models.Movement.created_at.desc())
        .limit(20)
    )
    movements = result.scalars().all()
    return [
        {
            "id": m.id,
            "product": m.product.name,
            "type": m.type,
            "quantity": m.quantity,
            "created_at": m.created_at.strftime("%H:%M:%S")
        } for m in movements
    ]

# Тестовые данные (вызывается через API /api/seed)
@app.post("/api/seed")
async def seed_data(db: AsyncSession = Depends(get_db)):
    # Проверяем, есть ли уже товары в базе
    existing = await db.execute(select(models.Product))
    if existing.scalars().first():
        return {"status": "already seeded"}

    p1 = models.Product(sku="SKU-101", name="Органайзер", category="Хранение")
    p2 = models.Product(sku="SKU-102", name="Кошелек", category="Аксессуары")
    w1 = models.Warehouse(name="Магазин 01 (FBS)", type="FBS")
    w2 = models.Warehouse(name="Склад WB (FBO)", type="FBO")
    db.add_all([p1, p2, w1, w2])
    await db.flush()

    s1 = models.Stock(product_id=p1.id, warehouse_id=w1.id, quantity=10)
    s2 = models.Stock(product_id=p2.id, warehouse_id=w1.id, quantity=5)
    db.add_all([s1, s2])
    await db.commit()
    return {"status": "seeded"}